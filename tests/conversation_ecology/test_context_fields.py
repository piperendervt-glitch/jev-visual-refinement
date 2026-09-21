"""Existing evidence mass core with synthetic physical roots, no models/devices."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(1,str(ROOT))
from conversation_ecology.context.field_adapter import field_snapshot


def inputs(count=1):
    h=dict(id='hyp',space='place',scope='session',subject='synthetic-room',facet='scene',value='inside',reference_mode='observed',label='Synthetic room')
    records=[]
    for i in range(count):
        root='synthetic:1:video:cam:0'
        obs=dict(id=f'o{i}',kind='observation',revision=1,epoch=1,dependencies={},scope='session',subject='synthetic-room',reference_mode='observed',
                 input_roots=[root],evidence_roots=[root],root_sources={root:dict(modality='video',stream='cam',interval=[0,1],pts=1,time_base=[1,1])},citations={root:1},input_cutoff_s=1)
        ev=dict(id=f'e{i}',kind='evidence_evaluation',revision=1,epoch=1,dependencies={obs['id']:1},evaluation_kind='evidence',observation_id=obs['id'],hypothesis_id='hyp',q=1,r=1,a=1,p_support=1,p_contradict=0,accepted_wall_s=0)
        records.extend(dict(record=r,available_cursor=1,source_cutoff=1) for r in (obs,ev))
    return records,[h]


class FieldContracts(unittest.TestCase):
    def test_CTX10_A03_B07_duplicate_root_max_before_decay(self):
        records,h=inputs();a=field_snapshot(records,h,cutoff=1,cursor=1)
        records,h=inputs(100);b=field_snapshot(records,h,cutoff=1,cursor=1)
        self.assertEqual(a['spaces'],b['spaces']);self.assertEqual(a['spaces']['place']['UNKNOWN'],.5)
        self.assertEqual(a['spaces']['person']['UNKNOWN'],1);self.assertEqual(a['spaces']['conversation']['UNKNOWN'],1)
    def test_CTX12_A07_support_contradiction_not_top1(self):
        records,h=inputs(2);records[-1]['record']['p_support']=0;records[-1]['record']['p_contradict']=1
        result=field_snapshot(records,h,cutoff=1,cursor=1);row=result['spaces']['place']['hypotheses'][0]
        self.assertEqual((row['S'],row['R'],row['E']),(.5,.5,0));self.assertTrue(row['conflict']);self.assertEqual(result['spaces']['place']['UNKNOWN'],1)
    def test_A08_B09_generated_root_denied(self):
        records,h=inputs();records[0]['record']['kind']='digest'
        with self.assertRaisesRegex(ValueError,'non_evidence_root_denied'):field_snapshot(records,h,cutoff=1,cursor=1)
        records,h=inputs();records[0]['record']['root_sources']['synthetic:1:video:cam:0']['stream']='wrong'
        with self.assertRaisesRegex(ValueError,'nonphysical_root'):field_snapshot(records,h,cutoff=1,cursor=1)
    def test_asof_evaporation_and_old_snapshot_isolation(self):
        records,h=inputs();a=field_snapshot(records,h,cutoff=1,cursor=1)
        later=field_snapshot(records,h,cutoff=13,cursor=1);self.assertEqual(later['spaces']['place']['hypotheses'][0]['S'],.5)
        self.assertEqual(field_snapshot(records,h,cutoff=1,cursor=0)['spaces']['place']['UNKNOWN'],1)
        self.assertEqual(a,field_snapshot(records,h,cutoff=1,cursor=1))


if __name__=='__main__':unittest.main()
