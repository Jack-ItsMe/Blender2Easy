import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

// Run with node --experimental-vm-modules tests/frontend/ui-checks.mjs.
// Real Three.js geometry and raycasting; no browser/WebGL mocks are needed.
const root=path.join(path.dirname(fileURLToPath(import.meta.url)),'../../skills/blender2easy/editor/web');
const context=vm.createContext({console,URL,URLSearchParams,Intl,navigator:{languages:['zh-CN']},setTimeout,clearTimeout,performance,TextDecoder,TextEncoder});
const modules=new Map();
async function getModule(filename) {
  filename=path.resolve(filename);
  if(!modules.has(filename)) modules.set(filename,new vm.SourceTextModule(await readFile(filename,'utf8'),{context,identifier:filename}));
  return modules.get(filename);
}
function resolve(spec,from) {
  if(spec==='three') return path.join(root,'vendor/three/build/three.module.js');
  if(spec.startsWith('three/addons/')) return path.join(root,'vendor/three/examples/jsm',spec.slice(13));
  if(spec.startsWith('/')) return path.join(root,spec.slice(1));
  return path.resolve(path.dirname(from),spec);
}
const module=await getModule(path.join(root,'viewport.js'));
await module.link((spec,ref)=>getModule(resolve(spec,ref.identifier)));await module.evaluate();
const {Viewport}=module.namespace;
const THREE=(await getModule(path.join(root,'vendor/three/build/three.module.js'))).namespace;
const content=new THREE.Group(),owner=new THREE.Group();owner.userData.editorId='Source part / 原件';
owner.position.set(2,3,4);owner.rotation.z=Math.PI/2;owner.scale.set(2,2,2);
const shared=new THREE.MeshStandardMaterial({color:0x334455,transparent:false,opacity:0.85});
const mesh=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),shared);owner.add(mesh);content.add(owner);
const other=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),shared);other.userData.editorId='Other';other.position.set(20,0,0);content.add(other);
const hidden=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),shared);hidden.userData.editorId='Hidden';hidden.visible=false;content.add(hidden);
content.updateMatrixWorld(true);
let picked=null,selected=null;
const camera=new THREE.PerspectiveCamera(45,1,.01,100);camera.position.set(2,3,10);camera.lookAt(2,3,4);camera.updateMatrixWorld(true);
const v=Object.create(Viewport.prototype);
Object.assign(v,{content,objects:new Map([[owner.userData.editorId,owner],['Other',other]]),cameras:new Map(),cameraId:null,freeCamera:camera,helpers:new THREE.Group(),inspection:null,inspectionMode:null,inspectionPoints:[],inspectionMarkers:new THREE.Group(),measurementLabel:{hidden:true,style:{}},surfaceCursor:{hidden:true},visibilityBaseline:new Map(),xrayMaterials:new Map(),xrayEnabled:false,isolationIds:null,renderer:{domElement:{style:{},getBoundingClientRect:()=>({left:0,top:0})}},rect:{x:0,y:0,width:100,height:100},pointer:new THREE.Vector2(),raycaster:new THREE.Raycaster(),select:id=>{selected=id;},onSelect:id=>{selected=id;},onSurfacePick:point=>{picked=point;}});
v.helpers.visible=false;
v.configureInspection({tools:['point','measure','isolate','xray'],object_ids:[owner.userData.editorId]});
v.setInspectionMode('point');v.pick({clientX:50,clientY:50});
assert.equal(picked.object_id,'Source part / 原件','child triangle hit resolves stable source ID');
assert.ok(Math.abs(picked.world[2]-5)<1e-6,'ray hit is actual front surface, not object center');
assert.ok(Math.abs(picked.local[2]-.5)<1e-6,'local coordinates use mapped source transform');
const pointA=picked,pointB={object_id:picked.object_id,local:[.5,0,.5],world:[2,4,5]};
v.setInspectionPoints([pointA,pointB]);
assert.equal(v.inspectionMarkers.children.length,3,'two markers plus measurement line');
assert.equal(v.measurementLabel.hidden,false);assert.match(v.measurementLabel.textContent,/1 预览单位/);
let disposed=0;
v.setXray(true);const clone=mesh.material;clone.addEventListener('dispose',()=>disposed++);
assert.notEqual(clone,shared);assert.equal(other.material,shared,'out-of-scope material unchanged');
assert.equal(shared.opacity,.85,'shared native baseline unchanged');assert.equal(clone.depthWrite,false);
v.setXray(false);assert.equal(mesh.material,shared);assert.equal(disposed,1,'temporary material disposed');
v.setIsolation([owner.userData.editorId]);assert.equal(mesh.visible,true);assert.equal(other.visible,false);
v.setIsolation(null);assert.equal(other.visible,true);assert.equal(hidden.visible,false,'restore original hidden state');
v.configureInspection({tools:['measure'],object_ids:['Other']});picked=null;selected=null;v.setInspectionMode('measure');v.pick({clientX:50,clientY:50});
assert.equal(picked,null);assert.equal(selected,null,'out-of-scope surface cannot be selected');
v.configureInspection(null);v.pick({clientX:50,clientY:50});assert.equal(selected,owner.userData.editorId,'legacy selection remains');
v.inspectionPoints=[pointA,pointB];v.frame=1;v.transform={dragging:false};v.project={scene:{animation:[]}};v.setFrame(2);
assert.equal(v.inspectionPoints.length,0,'frame changes clear surface samples');
const html=await readFile(path.join(root,'index.html'),'utf8'),review=await readFile(path.join(root,'review.js'),'utf8');
for(const id of ['findings','inspection-tools','inspection-point','inspection-measure','inspection-isolate','inspection-xray','reference-surface','checkpoints','confirm-btn']) assert.ok(html.includes(`id="${id}"`),`retains ${id}`);
assert.ok(review.includes('finding_id'));assert.ok(review.includes('onSurfacePick:selectSurface'));
// Exercise actual review state transitions with rendering/network seams stubbed.
// This protects coordinates from silently surviving changes to the geometry they sampled.
const reviewContext=vm.createContext({console,URLSearchParams,Intl,navigator:{languages:['zh-CN']},location:{search:''},structuredClone,setTimeout:()=>1,clearTimeout:()=>{},document:{documentElement:{dataset:{},style:{}},querySelectorAll:()=>[],getElementById:()=>({})}});
const reviewSource=review.replace("import {Viewport} from '/viewport.js';",'').replace(/\nboot\(\);\s*$/,'')+`
  updatePosition=()=>{}; updateLocks=()=>{}; renderControls=()=>{}; renderCompare=()=>{}; status=()=>{};
  stopPlayback=()=>{}; displayProject=async()=>{}; previewCandidate=async()=>{}; renderInspection=()=>{};
  revealFeedback=()=>{};
  export {state,changeValue,resetValues,toggleComparison,toggleInspection,clearSurfacePoints,annotationText,selectSurface,findingEvidenceState};
  export function setTestViewport(value){viewport=value;}
`;
const reviewModules=new Map();
async function getReviewModule(filename) {
  filename=path.resolve(filename);
  if(!reviewModules.has(filename)) reviewModules.set(filename,new vm.SourceTextModule(await readFile(filename,'utf8'),{context:reviewContext,identifier:filename}));
  return reviewModules.get(filename);
}
const rm=new vm.SourceTextModule(reviewSource,{context:reviewContext,identifier:path.join(root,'review.js')});
await rm.link((spec,ref)=>getReviewModule(resolve(spec,ref.identifier)));await rm.evaluate();
const ui=rm.namespace;
let displayedPoints=[];
ui.setTestViewport({setInspectionPoints:points=>{displayedPoints=points;},configureInspection:()=>{},setInspectionMode:()=>{},setIsolation:()=>{},setXray:()=>{}});
ui.state.review={status:'pending',request:{inspection:{tools:['point','measure','isolate','xray'],object_ids:[pointA.object_id]},focus:{object_ids:[pointA.object_id],source_range:[1,48]}}};
ui.state.current={project:{}};ui.state.frame=1;ui.state.previewValid=true;ui.state.defaults={width:1};ui.state.values={width:2};
const saved={source_frame:1,object_id:pointA.object_id,points:[pointA,pointB],measurement:{distance:1,units:'preview_world_units',verified_geometry:false}};
function place(){ui.state.annotation=structuredClone(saved);displayedPoints=ui.state.annotation.points;}
place();ui.changeValue('width',3);assert.equal(ui.state.annotation.points,undefined);assert.equal(ui.state.annotation.measurement,undefined);assert.equal(displayedPoints.length,0,'parameter change clears rendered samples');
place();await ui.resetValues();assert.equal(ui.state.values.width,1);assert.equal(ui.state.annotation.points,undefined,'reset clears sampled geometry');
place();await ui.toggleComparison();assert.equal(ui.state.annotation.points,undefined,'comparison clears sampled geometry');
ui.state.previewValid=true;place();ui.toggleInspection('xray');assert.equal(ui.state.annotation.points.length,2,'xray keeps samples');
ui.toggleInspection('isolate');assert.equal(ui.state.annotation.points.length,2,'isolation keeps samples');
ui.state.inspectionTool='measure';ui.state.previewBusy=true;ui.state.annotation=null;ui.selectSurface(pointA);assert.equal(ui.state.annotation,null,'pending geometry rejects new samples');ui.state.previewBusy=false;
ui.state.review.status='submitted';ui.state.review.response={annotation:structuredClone(saved)};ui.state.annotation=structuredClone(ui.state.review.response.annotation);
assert.match(ui.annotationText(ui.state.review.response.annotation),/1 预览单位/,'saved receipt formats measurement');
await ui.toggleComparison();assert.equal(ui.state.annotation.points,undefined);assert.equal(ui.state.review.response.annotation.points.length,2,'view changes never mutate saved response');assert.equal(ui.state.review.response.annotation.measurement.distance,1);
assert.match(ui.annotationText({...saved,measurement:{distance:.025,units:'m',display_distance:25,display_units:'mm'}}),/25 mm（模型尺寸）/,'receipt uses server-normalized model display units');
// Orbit/camera changes are view-only and retain the actual Three.js marker set.
v.setInspectionPoints([pointA,pointB]);v.orbit={enabled:true};v.transform={camera:null,detach:()=>{}};v.interaction={helpers:false};v.grid={};v.resize=()=>{};
v.scene=new THREE.Scene();v.setCamera(null);assert.equal(v.inspectionPoints.length,2,'camera orbit preserves surface samples');
v.project={units:'mm',scene:{}};v.setInspectionPoints([pointA,pointB]);assert.equal(v.measurementLabel.textContent,'1000 mm','procedural preview meters convert to declared millimeters');assert.match(v.measurementLabel.title,/模型尺寸/);
v.project={units:'mm',source:{blend:'native.blend'}};v.setInspectionPoints([pointA,pointB]);assert.equal(v.measurementLabel.textContent,'1 预览单位','native dimensions do not assume Blender export unit mapping');
console.log('PASS: actual ray picking/source identity, measurement, scoped tools/effect restoration, frame and parameter/reset/comparison invalidation, view-only preservation, immutable saved receipt and legacy selection.');
ui.state.review.request.evidence={findings:[{id:'baseline-finding'}]};
ui.state.defaults={width:1};ui.state.values={width:1};ui.state.compare=false;
assert.equal(ui.findingEvidenceState(),'original');
ui.state.values.width=2;assert.equal(ui.findingEvidenceState(),'candidate-unchecked','candidate edits cannot inherit original diagnostic validity');
ui.state.compare=true;assert.equal(ui.findingEvidenceState(),'original','original view identifies its own evidence');
ui.state.compare=false;ui.state.values.width=1;assert.equal(ui.findingEvidenceState(),'original','reset returns to checked input values');
ui.state.review.request.evidence={};assert.equal(ui.findingEvidenceState(),'none','no invented diagnosis status');
console.log('PASS: diagnostic evidence freshness follows displayed original/candidate and parameter reset.');
ui.state.review.status='pending';ui.state.previewBusy=false;ui.state.previewValid=true;ui.state.inspectionTool='point';ui.state.annotation=null;ui.state.compare=true;
ui.selectSurface(pointA);assert.equal(ui.state.annotation.preview_variant,'original','surface pick records the actually displayed original');
ui.clearSurfacePoints();assert.equal(ui.state.annotation.preview_variant,undefined,'cleared samples cannot keep obsolete origin');
ui.state.compare=false;ui.selectSurface(pointA);assert.equal(ui.state.annotation.preview_variant,'candidate','candidate pick is distinguishable from original');
console.log('PASS: surface samples preserve displayed geometry origin and clear it with stale coordinates.');
