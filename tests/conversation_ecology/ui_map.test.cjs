const {test}=require('node:test'),assert=require('node:assert/strict');
const {MapState}=require('../../ui/conversation_ecology/map-state.js');
const view=(cursor=0,session_id='s')=>({session_id,epoch:1,cursor,nodes:[{id:'a',revision:cursor}],edges:[],history:[]});
test('duplicate and old delivery preserve current view',()=>{const s=new MapState();s.snapshot(view());const d={session_id:'s',epoch:1,base:0,cursor:1,update_id:'u',snapshot:view(1)};assert.equal(s.delta(d),'applied');assert.equal(s.delta(d),'duplicate_or_old');assert.equal(s.live.cursor,1);});
test('missing sequence requests snapshot; wrong session rejected',()=>{const s=new MapState();s.snapshot(view());assert.equal(s.delta({session_id:'s',epoch:1,base:1,cursor:2,update_id:'u'}),'gap');assert.equal(s.live.cursor,0);assert.equal(s.delta({session_id:'other',epoch:1}),'wrong_session');});
test('frozen map and detail share one immutable cursor',()=>{const s=new MapState();s.snapshot(view());s.freeze();s.snapshot(view(3));assert.equal(s.view.nodes[0].revision,0);assert.equal(s.incoming,3);s.latest();assert.equal(s.view.cursor,3);});
test('session switch clears selection and fixed cursor',()=>{const s=new MapState();s.snapshot(view());s.selected='a';s.freeze();s.snapshot(view(0,'b'));assert.equal(s.selected,null);assert.equal(s.fixed,null);});
test('edge arriving before endpoint is withheld',()=>{const s=new MapState();const v=view();v.edges=[{source:'a',target:'b'}];s.snapshot(v);assert.equal(s.edges().length,0);v.nodes.push({id:'b'});s.snapshot(v);assert.equal(s.edges().length,1);});
