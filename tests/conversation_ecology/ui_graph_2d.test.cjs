const {test}=require('node:test'),assert=require('node:assert/strict');
const {GRAPH_PROFILE,graphPixels,graphFit,graphZoom,graphHit,CameraMotion}=require('../../ui/conversation_ecology/map-camera.js');
test('G2D sizes grow continuously, monotonically and remain bounded at all camera limits',()=>{
  for(const kind of ['Evidence','Claim','Entity','OpenIssue','Aggregate','label','region']){
    let previous=graphPixels(kind,.5);for(let s=.5;s<=8;s+=.01){const p=graphPixels(kind,s);assert.ok(p>=previous);assert.ok(p-previous<.5);previous=p;}
    const range=GRAPH_PROFILE.diameters[kind]||GRAPH_PROFILE[kind];assert.ok(previous<=range[1]);assert.equal(graphPixels(kind,1),range[0]);
  }
});
test('G2D CSS conversion applies world scale once for all viewport widths',()=>{
  for(const base of [.39,1.024,1.92])for(const zoom of [.5,1,2,4,8])for(const kind of ['Entity','Evidence','label','region']){
    const pixel=graphPixels(kind,zoom),world=pixel/(base*zoom);assert.ok(Math.abs(world*base*zoom-pixel)<1e-10);
  }
});
test('G2D pointer anchored wheel clamps and leaves the same world point beneath pointer',()=>{
  const c={zoom:1.7,x:80,y:-20},x=300,y=200;
  for(const factor of [.001,.8,1.2,100]){const n=graphZoom(c,factor,x,y,.8);assert.ok(n.zoom>=.4&&n.zoom<=6.4);assert.ok(Math.abs((x-n.x)/n.zoom-(x-c.x)/c.zoom)<1e-9);assert.ok(Math.abs((y-n.y)/n.zoom-(y-c.y)/c.zoom)<1e-9);}
});
test('G2D fit handles empty and nonfinite data, centers all valid points without mutation',()=>{
  const p=[{x:20,y:40},{x:1200,y:620},{x:NaN,y:3}],before=structuredClone(p),f=graphFit(p);assert.deepEqual(p,before);assert.equal(f.x+610*f.zoom,500);assert.equal(f.y+330*f.zoom,250);assert.ok(f.zoom<1);assert.deepEqual(graphFit([]),{zoom:1,x:0,y:0});
});
test('G2D dense hit uses nearest visible stable ID independent of DOM order and resolves ties',()=>{
  const ns=[{id:'b',kind:'Entity'},{id:'a',kind:'Entity'}],ps=new Map([['a',{x:10,y:10}],['b',{x:14,y:10}]]);
  assert.equal(graphHit(ns,ps,10,10,1,1),'a');assert.equal(graphHit(ns,ps,14,10,1,1),'b');assert.equal(graphHit(ns,ps,12,10,1,1),'a');assert.equal(graphHit(ns.reverse(),ps,12,10,1,1),'a');assert.equal(graphHit(ns,ps,30,30,1,1),null);
});
function clock(){let now=0,id=0;const jobs=new Map(),draws=[];const camera=new CameraMotion(v=>draws.push(v),{now:()=>now,schedule:f=>(jobs.set(++id,f),id),clear:id=>jobs.delete(id)});return {camera,jobs,draws,tick(dt){now+=dt;const fs=[...jobs.values()];jobs.clear();fs.forEach(f=>f());}};}
test('G2D finite camera reaches target and has no idle frame reservations',()=>{
  const h=clock(),to={zoom:4,x:20,y:30};h.camera.move({zoom:1,x:0,y:0},to);for(let i=0;i<10;i++)h.tick(16);assert.deepEqual(h.draws.at(-1),to);assert.equal(h.jobs.size,0);assert.equal(h.camera.pending,null);const n=h.draws.length;h.tick(2000);assert.equal(h.draws.length,n);
});
test('G2D manual gesture, session and dispose cancellation reject queued old camera callbacks',()=>{
  const h=clock();h.camera.move({zoom:1,x:0,y:0},{zoom:3,x:10,y:20});const old=h.jobs.values().next().value;h.tick(16);h.camera.cancel();const n=h.draws.length;old();h.tick(300);assert.equal(h.draws.length,n);assert.equal(h.jobs.size,0);assert.equal(h.camera.target,null);
});
test('G2D rapid wheel replacement keeps only latest camera; reduced motion has zero scheduled frames',()=>{
  const h=clock();for(let i=2;i<8;i++){h.camera.move({zoom:1,x:0,y:0},{zoom:i,x:0,y:0});assert.equal(h.jobs.size,1);}h.tick(160);assert.equal(h.draws.at(-1).zoom,7);h.camera.move(h.draws.at(-1),{zoom:2,x:3,y:4},true);assert.equal(h.jobs.size,0);assert.deepEqual(h.draws.at(-1),{zoom:2,x:3,y:4});
});
test('G2D graph display has no canonical storage or output API dependency',()=>{
  const source=require('node:fs').readFileSync(require('node:path').join(__dirname,'../../ui/conversation_ecology/map-camera.js'),'utf8');assert.doesNotMatch(source,/fetch\(|\/api\/|localStorage|indexedDB|ContextCommit/);
});
