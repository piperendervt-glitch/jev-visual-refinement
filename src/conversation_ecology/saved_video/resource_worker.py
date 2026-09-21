"""One model instance and one track reader, bounded JSON over inherited pipes."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from .media import SavedVideoSource,plain_path
from .models import LocalAnalyzers
from .runtime import configure_cache
from .resource_metrics import process_sample


class LaneAnalyzers(LocalAnalyzers):
    def prepare(self,kind,config):
        import torch
        import ctypes
        self.torch_threads=config['torch_threads'];self.asr_device=config['asr_device']
        self.asr_threads=config['asr_threads'];self.asr_compute_type=config['asr_compute_type']
        torch.set_num_threads(self.torch_threads);torch.set_num_interop_threads(config['torch_interop'])
        dll=Path(torch.__file__).parent/'lib'
        if os.name=='nt':
            self.dll_directory=os.add_dll_directory(str(dll))
            self.dll_handles=[ctypes.WinDLL(str(dll/n)) for n in ('cublas64_12.dll','cublasLt64_12.dll','cudnn64_9.dll')]
        if kind=='asr':
            from faster_whisper import WhisperModel
            self.asr=WhisperModel(str(self.root/'whisper-small'),device=self.asr_device,compute_type=self.asr_compute_type,
                                 cpu_threads=self.asr_threads,num_workers=1,local_files_only=True)
            actual=dict(device=self.asr.model.device,compute_type=self.asr.model.compute_type,
                        cpu_threads_configured=self.asr_threads,num_workers_configured=1,
                        num_workers_observed=getattr(self.asr.model,'num_workers',None))
        else:
            from transformers import AutoProcessor,Qwen3VLForConditionalGeneration
            self.processor=AutoProcessor.from_pretrained(str(self.root/'qwen3-vl-2b'),local_files_only=True,trust_remote_code=False)
            self.vlm=Qwen3VLForConditionalGeneration.from_pretrained(str(self.root/'qwen3-vl-2b'),
                local_files_only=True,trust_remote_code=False,dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda').eval()
            p=next(self.vlm.parameters());actual=dict(device=str(p.device),dtype=str(p.dtype),offload=False)
        actual.update(torch_threads=torch.get_num_threads(),torch_interop=torch.get_num_interop_threads(),
                      torch_cuda_runtime=torch.version.cuda,decoder_threads_configured=config['decoder_threads'],
                      omp=os.environ.get('OMP_NUM_THREADS'),mkl=os.environ.get('MKL_NUM_THREADS'),
                      native_active_threads='not_directly_observable')
        return actual


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--spec',required=True,type=Path);args=parser.parse_args()
    from .server import ROOT,SVBoundary
    spec_path=plain_path(args.spec).resolve()
    manual=spec_path.is_relative_to(ROOT/'artifacts/sv01/manual-local')
    if not manual and not spec_path.is_relative_to(ROOT/'artifacts/sv01/resource-r1'):raise ValueError('worker_spec_boundary')
    spec=json.loads(spec_path.read_text(encoding='utf-8'));kind=spec['lane']
    if kind not in ('asr','image') or not spec.get('load_ticket'):raise ValueError('worker_ticket')
    if manual:
        from .manual import settings, MODE
        profile,sha=settings()
        if spec.get('mode')!=MODE or spec.get('settings_sha256')!=sha or spec_path.parent.name!='content':raise ValueError('worker_manual_settings')
        ledger=spec_path.parent/'usage.json'
    else:profile=json.loads((ROOT/'config/sv01_resource_r1.json').read_text(encoding='utf-8'))
    config=profile['candidates'][spec['candidate']]
    from .grants import R1,resolve_route
    if not manual:ledger=resolve_route(ROOT,R1)['ledger']
    def verify_ticket(ident,stage):
        data=json.loads(ledger.read_text(encoding='utf-8'))
        if manual and (data.get('mode')!=MODE or data.get('settings_sha256')!=sha):raise ValueError('worker_manual_contract')
        if data.get('state')!='RUNNING' or not data.get('runtime_in_flight') or data.get('cohort')!=spec['cohort']:
            raise ValueError('worker_grant_not_running')
        tickets=[t for t in data['tickets'] if t['id']==ident and t['kind']==stage and t['lane']==kind
                 and t['worker']==spec['worker_id'] and t['cohort']==spec['cohort']]
        if len(tickets)!=1:raise ValueError('worker_unreserved_ticket')
    verify_ticket(spec['load_ticket'],'load')
    if manual:print(json.dumps(dict(stage='booted',pid=os.getpid())),flush=True)
    configure_cache(spec_path.parent/'cache'/spec['worker_id'])
    for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):
        os.environ[key]=str(config['asr_threads'] if kind=='asr' else config['torch_threads'])
    sys.dont_write_bytecode=True;sys.addaudithook(SVBoundary().guard)
    import faulthandler
    faulthandler.enable(file=sys.stderr,all_threads=True)
    model=LaneAnalyzers(spec['model_root']);start=time.monotonic();code=0;seen=set()
    def send(value):print(json.dumps(value,ensure_ascii=False,allow_nan=False),flush=True)
    try:
        actual=model.prepare(kind,config)
        # Import decoder libraries before any blocking Windows CRT stdin read.
        import av,numpy
        decoder=SavedVideoSource(profile|{'decoder_threads':config['decoder_threads']})
        send(dict(stage='ready',lane=kind,load_ticket=spec['load_ticket'],load_seconds=time.monotonic()-start,
                  actual=actual,metrics=process_sample(),worker_id=spec['worker_id']))
        while True:
            raw=sys.stdin.readline(65537)
            if not raw:break
            if len(raw)>65536:raise ValueError('ipc_request_size')
            job=json.loads(raw)
            if job['action']=='stop':break
            if job['action']!='decode':raise ValueError('worker_protocol')
            asset=job['asset'];asset['path']=plain_path(asset['path']).resolve()
            if manual:
                registry=json.loads((spec_path.parent/'assets.json').read_text(encoding='utf-8'))
                registered=registry.get(asset['id'],{})
                if asset['path'].parent!=spec_path.parent/'media' or registered!={'sha256':asset['sha256'],'file':asset['path'].name}:
                    raise ValueError('worker_manual_asset_boundary')
            elif not asset['path'].is_relative_to(ROOT/'artifacts/sv01/resource-r1') or asset['sha256'] not in profile['allowed_asset_sha256']:
                raise ValueError('worker_asset_boundary')
            before=process_sample();a=time.monotonic()
            packet=decoder.decode(asset,*job['interval'],job['envelope'],lane=kind)
            decoded=time.monotonic()
            send(dict(stage='decoded',provenance=packet.provenance,decode_start=a,decode_end=decoded,
                      input_available=bool(len(packet.pcm)) if kind=='asr' else packet.frame is not None))
            action=json.loads(sys.stdin.readline(65537))
            if action['action']=='cancel':continue
            ticket=action.get('ticket')
            if action['action']!='infer' or not ticket or ticket in seen:raise ValueError('inference_ticket')
            verify_ticket(ticket,'inference')
            if manual and len(seen)>=4096:seen.clear()  # Completed tickets are removed durably by the owner.
            seen.add(ticket);begin=time.monotonic();result=model.infer(kind,packet);end=time.monotonic()
            send(dict(stage='result',ticket=ticket,result=result,infer_start=begin,infer_end=end,before=before,after=process_sample()))
            del packet
    except BaseException as error:
        send(dict(stage='failed',reason=type(error).__name__+':'+str(error)[:300],metrics=process_sample()));code=2
    finally:
        model.close();send(dict(stage='closed',metrics=process_sample(),code=code));faulthandler.disable()
    return code
