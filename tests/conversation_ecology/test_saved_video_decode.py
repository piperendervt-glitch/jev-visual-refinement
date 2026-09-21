"""Generated media only. Real PyAV, no learned models or user media."""
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from conversation_ecology.saved_video.media import SavedVideoSource, probe
PROFILE=json.loads((ROOT/'config/sv01.json').read_text())


@unittest.skipUnless(importlib.util.find_spec('av'), 'installed PyAV required')
class DecodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):
        self.tmp.cleanup()
    def make(self, audio=True, offset=0, variable=False, silent=False):
        import av
        import numpy as np
        path=Path(self.tmp.name)/'generated.mkv'
        with av.open(str(path),'w') as c:
            v=c.add_stream('ffv1',rate=10);v.width=64;v.height=48;v.pix_fmt='yuv420p';v.time_base=Fraction(1,1000)
            a=c.add_stream('pcm_s16le',rate=48000) if audio else None
            if a:a.layout='mono'
            for n in range(30):
                f=av.VideoFrame.from_ndarray(np.full((48,64,3), n*5, dtype=np.uint8),format='rgb24')
                f.pts=5000+n*100+(20 if variable and n%2 else 0);f.time_base=Fraction(1,1000)
                for p in v.encode(f):c.mux(p)
                if a:
                    signal=np.zeros((1,4800),dtype=np.int16) if silent else (1000*np.sin(np.arange(4800)[None,:]*.1)).astype(np.int16)
                    af=av.AudioFrame.from_ndarray(signal,format='s16',layout='mono');af.sample_rate=48000
                    af.pts=240000+offset+n*4800;af.time_base=Fraction(1,48000)
                    for p in a.encode(af):c.mux(p)
            for p in v.encode():c.mux(p)
            if a:
                for p in a.encode():c.mux(p)
        meta=probe(path,PROFILE)
        return dict(id='synthetic',path=path,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),**meta)
    def packet(self,asset,start=.3,end=1.71337):
        return SavedVideoSource(PROFILE).decode(asset,start,end,dict(run_id='test',session_id='s',epoch=1,available_cursor=1))
    def test_nonzero_pts_pcm_cutoff_and_source_offsets(self):
        asset=self.make(offset=2400)
        p=self.packet(asset)
        self.assertGreater(asset['origin_s'],0)
        self.assertGreater(len(p.pcm),0)
        self.assertLessEqual(p.provenance['audio']['mapping'][-1]['end_exclusive_s'],1.71337)
        self.assertGreaterEqual(p.provenance['audio']['mapping'][0]['start_s'],.3)
        self.assertGreater(p.provenance['frame']['pts'],0)
        self.assertEqual(p.provenance['audio']['sample_rate'],16000)
        self.assertLessEqual(p.provenance['av_end_delta_s'],PROFILE['sync_tolerance_seconds'])
    def test_variable_pts_not_fps_invented(self):
        asset=self.make(variable=True)
        p=self.packet(asset)
        f=p.provenance['frame']
        self.assertAlmostEqual(f['media_s'],f['pts']*Fraction(*f['time_base'])-asset['origin_s'])
    def test_no_audio_distinct_from_silence(self):
        p=self.packet(self.make(audio=False))
        self.assertEqual(p.provenance['audio']['status'],'no_audio_track')
        self.assertEqual(len(p.pcm),0)
        p=self.packet(self.make(silent=True))
        self.assertEqual(p.provenance['audio']['status'],'digital_silence')
    def test_empty_interval_and_decoder_bound_reject(self):
        asset=self.make()
        with self.assertRaisesRegex(ValueError,'invalid_interval'):self.packet(asset,2,2)
        limited=SavedVideoSource({**PROFILE,'decoder_frame_limit':1})
        with self.assertRaisesRegex(ValueError,'decoder_frame_limit'):
            limited.decode(asset,.3,1.7,{})
    def test_corrupt_container_reject(self):
        path=Path(self.tmp.name)/'bad.mp4';path.write_bytes(b'not a movie')
        with self.assertRaisesRegex(ValueError,'corrupt_encrypted_or_unsupported_codec'):probe(path,PROFILE)

    def test_resource_track_readers_preserve_exact_pcm_and_frame(self):
        import numpy as np
        asset=self.make(offset=2400,variable=True);old=self.packet(asset)
        decoder=SavedVideoSource(PROFILE|{'decoder_threads':1})
        envelope=dict(run_id='test',session_id='s',epoch=1,available_cursor=1)
        audio=decoder.decode(asset,.3,1.71337,envelope,lane='asr')
        image=decoder.decode(asset,.3,1.71337,envelope,lane='image')
        np.testing.assert_array_equal(old.pcm,audio.pcm);np.testing.assert_array_equal(old.frame,image.frame)
        self.assertEqual(old.provenance['audio'],audio.provenance['audio'])
        self.assertEqual(old.provenance['frame'],image.provenance['frame'])
        self.assertIsNone(audio.frame);self.assertEqual(len(image.pcm),0);self.assertIsNone(image.provenance['audio'])

    def test_resource_reader_rejects_unknown_track_lane(self):
        with self.assertRaisesRegex(ValueError,'invalid_decode_lane'):
            SavedVideoSource(PROFILE).decode({},0,2,{},lane='sensor')

    def test_long_gop_profile_is_bounded_and_does_not_publish_preroll(self):
        import av
        import numpy as np
        path=Path(self.tmp.name)/'long-generated.mp4'
        with av.open(str(path),'w') as c:
            v=c.add_stream('libx264',rate=10);v.width=64;v.height=48;v.pix_fmt='yuv420p'
            v.options={'preset':'ultrafast','g':'100','sc_threshold':'0'}
            for n in range(1800):
                f=av.VideoFrame.from_ndarray(np.full((48,64,3),n%200,dtype=np.uint8),format='rgb24');f.pts=n
                for p in v.encode(f):c.mux(p)
            for p in v.encode():c.mux(p)
        profile=json.loads((ROOT/'config/sv01_long_l1.json').read_text())
        asset=dict(id='generated-long',path=path,sha256='synthetic',**probe(path,profile))
        class Counted(SavedVideoSource):
            maximum=0
            def bounded(self,count,frame,origin,start):
                self.maximum=max(self.maximum,count+1);super().bounded(count,frame,origin,start)
        decoder=Counted(profile)
        for start,end in [(0,2),(9.5,9.99),(19.5,20.5),(89.5,89.99),(178,180)]:
            packet=decoder.decode(asset,start,end,{})
            self.assertTrue(start<=packet.provenance['frame']['media_s']<=end)
            self.assertEqual(packet.provenance['audio']['status'],'no_audio_track')
        self.assertLessEqual(decoder.maximum,102)
        with self.assertRaisesRegex(ValueError,'preroll_limit'):SavedVideoSource(PROFILE).decode(asset,9.5,9.99,{})


if __name__=='__main__':unittest.main()
