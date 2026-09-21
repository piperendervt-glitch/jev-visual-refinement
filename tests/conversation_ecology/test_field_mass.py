"""MASS contracts using real unchanged numerical reducer, synthetic roots only."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(1,str(ROOT))
from conversation_ecology.mass_fixture import MassFixture
from conversation_ecology.mass_projection import project_mass,token,distribution_key
from conversation_ecology.map_server import MapApp

class FieldMass(unittest.TestCase):
    def view(self,provider):return project_mass(provider.snapshot())
    def values(self,view):return {n['id']:n['mass']['value'] for n in view['nodes']}
    def test_MASS01_explicit_snapshot_scope_hypothesis_not_name(self):
        f=MassFixture();v=f.snapshot();before=deepcopy(v);v['nodes'][0]['field_refs'][0]['hypothesis_id']='no-such-id';project_mass(v)
        self.assertEqual(v['nodes'][0]['mass']['status'],'invalid_reference');self.assertEqual(f.snapshot(),before)
        v=f.snapshot();v['field_snapshots'][0]['scope']='other';project_mass(v);self.assertTrue(all(n['mass']['value'] is None for n in v['nodes']))
    def test_MASS03_support_updates_whole_distribution_not_other_space(self):
        f=MassFixture();a=self.view(f);f.set_stage('boost');b=self.view(f);x,y=self.values(a),self.values(b)
        self.assertEqual((x['mass:A'],y['mass:A']),(.25,.5));self.assertLess(y['mass:B'],x['mass:B']);self.assertLess(y['mass:C'],x['mass:C']);self.assertEqual(y['mass:D'],x['mass:D'])
        ax={n['region']:n for n in a['nodes'] if n['kind']=='Unknown'};bx={n['region']:n for n in b['nodes'] if n['kind']=='Unknown'}
        self.assertEqual(ax['place']['id'],bx['place']['id']);self.assertLess(bx['place']['mass']['value'],ax['place']['mass']['value'])
        place=[n['mass'] for n in b['nodes'] if n['region']=='place' and n['mass']['status']=='available'];self.assertEqual(len({r['reference']['snapshot_token'] for r in place}),1);self.assertEqual({r['view_cursor'] for r in place},{b['cursor']})
    def test_MASS04_initial_zero_missing_invalid_expired_separate(self):
        f=MassFixture();f.set_stage('initial');v=self.view(f);self.assertEqual(v['nodes'][0]['mass']['value'],0);self.assertTrue(all(n['mass']['value']==1 for n in v['nodes'] if n['kind']=='Unknown'))
        for bad in [None,-1,2,float('nan'),float('inf'),True]:
            v=f.snapshot();s=v['field_snapshots'][0]['snapshot'];s['spaces']['place']['UNKNOWN']=bad
            # Invalid values don't silently become zero or 100%.
            project_mass(v);u=next(n for n in v['nodes'] if n['kind']=='Unknown' and n['region']=='place');self.assertIsNone(u['mass']['value']);self.assertIn(u['mass']['status'],['not_provided','invalid_reference'])
        v=f.snapshot();v['retention']='expired';project_mass(v);self.assertTrue(all(n['mass']['value'] is None for n in v['nodes']))
    def test_MASS05_unknown_unique_display_only_no_edges_or_canonical_writes(self):
        f=MassFixture();v=self.view(f);us=[n for n in v['nodes'] if n['kind']=='Unknown'];self.assertEqual(len(us),3);self.assertEqual(len({n['id'] for n in us}),3)
        self.assertTrue(all(n['canonical_id'] is None and n['display_only'] for n in us));self.assertEqual(v['edges'],[])
    def test_MASS06_07_08_neutral_duplicate_multiple_and_subset(self):
        f=MassFixture();v=self.view(f);self.assertEqual(v['nodes'][0]['mass']['value'],v['nodes'][4]['mass']['value']);self.assertEqual(v['nodes'][5]['mass']['status'],'multiple_references')
        self.assertTrue(all(n['mass']['value'] is None for n in v['nodes'] if n['kind'] in ('Entity','Evidence','OpenIssue')))
        partial=f.snapshot();partial['nodes']=partial['nodes'][:1];project_mass(partial);self.assertEqual(partial['nodes'][0]['mass'],v['nodes'][0]['mass'])
    def test_MASS11_support_contradiction_decay_replay_uses_source_time(self):
        f=MassFixture();seed=self.view(f);f.set_stage('boost');boost=self.view(f);f.set_stage('contra');contra=self.view(f);f.set_stage('decay');decay=self.view(f);f.set_stage('replay');replay=self.view(f)
        self.assertLess(self.values(contra)['mass:A'],self.values(boost)['mass:A']);self.assertLess(self.values(decay)['mass:A'],self.values(boost)['mass:A']);self.assertEqual(self.values(seed),self.values(replay));self.assertEqual(replay['nodes'][0]['mass']['source_time'],1)
        v=f.snapshot();v['nodes'][0]['availability']='deleted';project_mass(v);self.assertEqual(v['nodes'][0]['mass']['status'],'unavailable')
    def test_MASS01_snapshot_token_mismatch_rejected(self):
        f=MassFixture();v=f.snapshot();v['nodes'][0]['field_refs'][0]['snapshot_token']='old';project_mass(v);self.assertIsNone(v['nodes'][0]['mass']['value'])
    def test_MASS05_independent_scope_unknown_ids_not_merged(self):
        f=MassFixture();v=f.snapshot();other=deepcopy(v['field_snapshots'][0]);other['scope']='other';v['field_scopes']=[v['scope'],'other'];v['field_snapshots'].append(other);project_mass(v)
        us=[n for n in v['nodes'] if n['kind']=='Unknown'];self.assertEqual(len(us),6);self.assertEqual(len({n['id'] for n in us}),6)
    def test_MASS14_map_api_no_output_or_pipeline_meaning_side_effects(self):
        app=MapApp();before=deepcopy(app.state());v=app.map_action({'action':'mass_start','dense':True})['view'];self.assertEqual(len(v['nodes']),203);self.assertEqual(len(v['mass_distributions']),3)
        for step in ('boost','contra','decay','replay'):v=app.map_action({'action':'mass_step','stage':step})['view'];self.assertEqual(v['pipeline']['records'],[])
        self.assertEqual(app.state(),before);self.assertIsNone(app.store);self.assertEqual(app.map_draws,set())
    def test_MASS16_fixture_finite_and_readonly_poll(self):
        f=MassFixture();before=f.snapshot();self.view(f);self.view(f);self.assertEqual(f.snapshot(),before)
        for _ in range(99):f.set_stage('boost')
        with self.assertRaisesRegex(ValueError,'capacity'):f.set_stage('boost')
    def test_MASS15_http_new_fixture_actions_and_asset(self):
        from test_context_http import HttpContracts
        from urllib.request import Request,urlopen
        server=HttpContracts();server.setUp()
        try:
            self.assertIn(b'MassMotion',server.get('/map-mass.js'))
            views=[]
            for body in ({'action':'mass_start'},{'action':'mass_step','stage':'boost'}):
                request=Request(server.base+'/api/map/action',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':server.base,'X-C0-Token':server.server.app.token},method='POST')
                with urlopen(request,timeout=3) as response:views.append(json.load(response)['view'])
            self.assertEqual([self.values(v)['mass:A'] for v in views],[.25,.5])
            self.assertEqual(server.server.app.map_draws,set())
        finally:server.tearDown()

if __name__=='__main__':unittest.main()
