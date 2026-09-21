// Execute actual map.js lifecycle handlers in a DOM/transport harness.
// Synthetic pageshow/pagehide are not proof of real Chrome BFCache behavior.
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function setup(bridge=false){
  class Element extends EventTarget{constructor(){super();this.dataset={};this.children=[];this.style={};this.value='';}append(...items){this.children.push(...items);}before(){}after(){}replaceChildren(){this.children=[];}}
  const elements=new Map(),window=new EventTarget(),document=new EventTarget();document.visibilityState='visible';document.getElementById=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};document.createElement=()=>new Element();document.querySelectorAll=()=>[];document.querySelector=()=>bridge?{content:'synthetic-owner'}:null;
  let reloads=0,disposed=0,aborts=0;const intervals=new Map();
  class State{constructor(){this.live=null;this.view=null;}}
  class Layout{constructor(){this.points=new Map();this.key='s';this.ticks=0;} }
  class Runner{constructor(){this.samples=[];this.pending=null;}stop(){this.pending=null;}}
  class Camera{constructor(){this.samples=[];this.pending=null;this.frames=0;}cancel(){this.pending=null;}}
  class Renderer{clear(){}}
  class Pipeline{constructor(){this.diagnostics=null;}dispose(){disposed++;}}
  class Gesture{cancel(){}}
  const ctx=vm.createContext({document,window,MapState:State,LayoutState:Layout,LayoutRunner:Runner,CameraMotion:Camera,MapRenderer:Renderer,PipelineView:Pipeline,NodeGesture:Gesture,AbortController,
    LAYOUT_PROFILE:{version:'test'},GRAPH_PROFILE:{},matchMedia:()=>new EventTarget(),setInterval:f=>{intervals.set(intervals.size+1,f);return intervals.size;},clearInterval:id=>intervals.delete(id),
    cancelAnimationFrame(){aborts++;},fetch:()=>new Promise(()=>{}),location:{reload(){reloads++;}},console,performance,Date,structuredClone});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../../ui/conversation_ecology/map-mass.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../../ui/conversation_ecology/process-history.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../../ui/conversation_ecology/map.js'),'utf8'),ctx);
  const fire=(name,persisted=false)=>{const event=new Event(name);Object.defineProperty(event,'persisted',{value:persisted});window.dispatchEvent(event);};
  return{fire,counts:()=>({reloads,disposed,aborts}),ctx};
}
test('UR08 map-only persisted route reloads once after actual disposal handler',()=>{const h=setup();h.fire('pageshow');assert.equal(h.counts().reloads,0);h.fire('pagehide',true);assert.equal(h.counts().disposed,1);assert.equal(vm.runInContext('uiEvents.signal.aborted',h.ctx),true);h.fire('pageshow',true);assert.equal(h.counts().reloads,1);h.fire('pagehide',true);assert.equal(h.counts().disposed,1);});
test('UR08 map script leaves persisted bridge recovery with its existing media owner handler',()=>{const h=setup(true);h.fire('pagehide',true);h.fire('pageshow',true);assert.equal(h.counts().disposed,1);assert.equal(h.counts().reloads,0);});
