"""Display-only DEMO structure and canonical/output isolation."""
import json
import sys
from pathlib import Path
import unittest
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from conversation_ecology.map_projection import DemoProvider
from conversation_ecology.map_server import MapApp


class DynamicMapTests(unittest.TestCase):
    def test_hub_keeps_all_canonical_nodes_and_source_fields(self):
        provider=DemoProvider();provider.start(True)
        for _ in range(20):provider.step('add')
        before=json.dumps(provider.view['nodes'],sort_keys=True)
        provider.step('hub')
        self.assertEqual(len(provider.view['nodes']),200)
        self.assertEqual(len(provider.view['edges']),199)
        self.assertEqual({e['target'] for e in provider.view['edges']},{'person-0'})
        self.assertEqual(before,json.dumps(provider.view['nodes'],sort_keys=True))

    def test_map_draw_is_not_c0_commit_or_ack_and_demo_never_opens_store(self):
        app=MapApp();app.map_action({'action':'demo','dense':True})
        before=app.state();view=app.provider.snapshot()
        for _ in range(24):app.map_action({'action':'map_draw','session_id':view['session_id'],'cursor':view['cursor']})
        self.assertEqual(app.state(),before)
        self.assertEqual(app.provider.snapshot(),view)
        self.assertEqual(len(app.map_draws),1)
        self.assertIsNone(app.store)

    def test_same_version_draw_does_not_change_context_semantic_records(self):
        from conversation_ecology.context.store import ContextStore
        from conversation_ecology.context.provider import ContextProvider
        from conversation_ecology.hearing.coordinator import HearingCoordinator
        root=Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(dir=root/'artifacts') as tmp:
            app=MapApp();app.store=ContextStore(Path(tmp)/'state.sqlite')
            try:
                app.coordinator=HearingCoordinator(app.store,'dyn-context');app.coordinator.start()
                app.provider=ContextProvider(app.coordinator)
                tables=['events','item_versions','current_items','proposals','context_commits',
                        'projections','consumers','response_commits','deliveries','acknowledgements']
                def semantic():return {t:[tuple(r) for r in app.store.db.execute('SELECT * FROM '+t)] for t in tables}
                before=semantic();view=app.provider.snapshot()
                for _ in range(24):app.map_action({'action':'map_draw','session_id':view['session_id'],'cursor':view['cursor']})
                self.assertEqual(semantic(),before)
                self.assertEqual(app.provider.snapshot(),view)
            finally:app.store.close()


if __name__=='__main__':unittest.main()
