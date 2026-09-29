import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const base=path.join(path.dirname(fileURLToPath(import.meta.url)),'../../skills/blender2easy/editor/web/');
const {messages}=await import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(base+'locales/review.js','utf8')).toString('base64'));
let locale='en';
class Element {
  constructor(id=''){Object.assign(this,{id,dataset:{},attributes:{},children:[],queries:new Map(),value:'',textContent:'',hidden:false,style:{},classList:{toggle(){}},selectionStart:2,selectionEnd:4,selectionDirection:'forward'});}
  setAttribute(key,value){this.attributes[key]=String(value);} getAttribute(key){return this.attributes[key]??null;} removeAttribute(key){delete this.attributes[key];}
  querySelectorAll(selector){return this.queries.get(selector)||[];} querySelector(selector){return this.querySelectorAll(selector)[0]||null;} closest(){return null;}
  append(...items){this.children.push(...items);} replaceChildren(...items){this.children=items;} getBoundingClientRect(){return {width:400,height:300};}
  setSelectionRange(start,end,direction){Object.assign(this,{selectionStart:start,selectionEnd:end,selectionDirection:direction});}
}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);};
get('workspace').dataset.inspector='closed';get('inspector-toggle').queries.set('.toggle-label',[new Element()]);get('copy-fallback').hidden=true;get('feedback-note').value='User note 中文 stays exactly';
const wrapper=new Element(),number=new Element(),range=new Element(),limits=[new Element(),new Element()];
wrapper.dataset.control='height';number.value='1.';range.value='1.5';wrapper.queries.set('input[type=range]',[range]);wrapper.queries.set('.control-limits span',limits);get('controls').queries.set('[data-control]',[wrapper]);
const checkpoint=new Element();checkpoint.dataset.checkpointId='cp';get('checkpoints').queries.set('[data-checkpoint-id]',[checkpoint]);
const finding=new Element();finding.dataset.findingId='finding';get('findings').queries.set('[data-finding-id]',[finding]);
const context=vm.createContext({console,structuredClone,URLSearchParams,location:{search:''},setTimeout,clearTimeout,registerMessages(){},initPreferences(){},translatePage(){},onLocaleChange(){},localizeError:error=>error?.message||String(error),formatNumber:(value,options)=>new Intl.NumberFormat(locale,options).format(value),messages,t:(key,params={})=>{assert.ok(messages[locale][key],key);return messages[locale][key].replace(/\{([A-Za-z][\w]*)\}/g,(all,name)=>String(params[name]??all));},document:{getElementById:get,createElement:()=>new Element(),createTextNode:text=>({textContent:text})}});
vm.runInContext(fs.readFileSync(base+'review.js','utf8').replace(/^import .*;\r?\n/gm,'').replace(/boot\(\);\s*$/,''),context);
vm.runInContext("Object.assign(state,{current:{project:{title:'Project 中文',scene:{objects:[{id:'obj',label:'Object 中文'}]}}},review:{status:'pending',agent_listening:true,request:{id:'req-id',title:'Agent title 中文',question:'Agent question 中文',stage:'motion',controls:[{id:'height',label:'Height 中文',kind:'number',min:0,max:10,step:.1,value:1}],focus:{source_range:[1,48],object_ids:['obj']},evidence:{references:[{id:'ref',title:'Reference 中文'}],checkpoints:[{id:'cp',title:'Checkpoint 中文',source_frame:24,reference_id:'ref'}],findings:[{id:'finding',title:'Finding 中文',source_frame:24,severity:'warning'}]},inspection:{object_ids:['obj'],tools:['point','measure']}}},values:{height:1.5},defaults:{height:1},frame:24,index:23,frames:Array.from({length:48},(_,i)=>i+1),annotation:{source_frame:24,object_id:'obj',reference_id:'ref',reference_uv:[.2,.3],points:[{object_id:'obj',point:[0,0,0]}]},compare:true,freeView:true,playing:true,referenceId:'ref',referenceOpen:true,inspectionTool:'point'}); connectionStatus('review.connection.interrupted');",context);
const before=vm.runInContext('JSON.stringify(state)',context),note=get('feedback-note');
for(const language of ['zh-Hans','zh-Hant','en']) {
 locale=language;vm.runInContext('refreshLocale()',context);
 assert.equal(vm.runInContext('JSON.stringify(state)',context),before);assert.equal(get('feedback-note'),note);assert.equal(note.value,'User note 中文 stays exactly');
 assert.equal(number.value,'1.');assert.equal(range.value,'1.5');assert.equal(get('request-title').textContent,'Agent title 中文');
 assert.equal(get('play-btn').attributes['aria-pressed'],'true');assert.equal(get('play-btn').attributes['aria-label'],messages[language]['review.pausePlayback']);
 assert.equal(get('connection-status').textContent,messages[language]['review.connection.interrupted']);assert.equal(get('checkpoints').querySelectorAll('[data-checkpoint-id]')[0],checkpoint);
}
console.log(JSON.stringify({status:'PASS',checks:'actual refreshLocale across three locales: state JSON, unsaved note, partial number input, slider, authored title, active playback, disconnected status, checkpoint DOM preserved'}));


let samples=[],focused=0;
context.testViewport={
  setInspectionPoints:points=>{samples=structuredClone(points);},
  inspectionMeasurement:()=>samples.length===2?{distance:1.25,display_distance:125,display_units:'cm',calibrated:false}:null,
  configureInspection(){},setInspectionMode(){},setIsolation(){},setXray(){},select(){},
  renderer:{domElement:{focus(){focused++;}}}
};
vm.runInContext("viewport=testViewport;Object.assign(state,{annotation:{source_frame:24,reference_id:'ref',reference_uv:[.2,.3]},inspectionTool:'measure',compare:false,playing:false,previewValid:true,previewBusy:false,nativeBusy:false,submitBusy:false});renderInspection();",context);
const hint=()=>get('inspection-hint').children.map(node=>node.textContent).join(' ');
const step=()=>get('inspection-hint').dataset.step;
const count=()=>vm.runInContext('state.annotation?.points?.length||0',context);
get('feedback-details').open=false;
const panelSnapshot=()=>({inspector:get('workspace').dataset.inspector,expanded:get('inspector-toggle').attributes['aria-expanded'],notes:get('feedback-details').open});
const pick=world=>{
 const panels=panelSnapshot();
 vm.runInContext("selectSurface("+JSON.stringify({object_id:'obj',local:world,world})+")",context);
 assert.deepEqual(panelSnapshot(),panels,'surface picking must preserve sidebar and note disclosure');
};
assert.equal(step(),'ready');assert.equal(get('inspection-restart').hidden,true);
pick([0,0,0]);assert.equal(count(),1);assert.equal(step(),'first');assert.match(hint(),/Point A recorded/);
vm.runInContext("state.review.request.inspection.tools.push('isolate')",context);
for(const reason of ['out-of-scope','no-surface','outside-view']) {
 const preserved=vm.runInContext('JSON.stringify(state)',context),points=JSON.stringify(samples),panels=panelSnapshot();
 vm.runInContext("handleInspectionMiss("+JSON.stringify(reason)+")",context);
 assert.equal(vm.runInContext('JSON.stringify(state)',context),preserved,'miss keeps all review data including A');
 assert.equal(JSON.stringify(samples),points);assert.deepEqual(panelSnapshot(),panels);
 assert.equal(step(),'first');assert.equal(get('inspection-hint').dataset.feedback,'miss');
 assert.match(hint(),/A is kept/);assert.match(hint(),/Use Isolate/);
}
for(const [language,fragment] of [['zh-Hans','A 点已保留'],['zh-Hant','A 點已保留'],['en','A is kept']]) {locale=language;vm.runInContext('renderInspection()',context);assert.ok(hint().includes(fragment));}
vm.runInContext("state.review.request.inspection.tools=state.review.request.inspection.tools.filter(tool=>tool!=='isolate');renderInspection()",context);
assert.ok(!hint().includes('Use Isolate'),'only suggest permitted tools');
const stableHintNodes=get('inspection-hint').children;
vm.runInContext('renderInspection()',context);assert.equal(get('inspection-hint').children,stableHintNodes,'unchanged step does not replace live content');
pick([1.25,0,0]);assert.equal(count(),2);assert.equal(step(),'complete');assert.match(hint(),/125 cm/);assert.equal(get('inspection-restart').hidden,false);
assert.equal(get('inspection-hint').dataset.feedback,'normal','valid B clears persistent miss');
locale='zh-Hant';vm.runInContext('renderInspection()',context);assert.match(hint(),/重新測量/);assert.equal(count(),2);
vm.runInContext("state.annotation.measurement={display_distance:1.2,display_units:'mm'};renderInspection();",context);assert.match(hint(),/1.2 mm/,'saved receipt value overrides live viewport');
vm.runInContext('delete state.annotation.measurement',context);
pick([2,0,0]);assert.equal(count(),1);assert.equal(step(),'first','third pick starts a new A');
assert.equal(vm.runInContext('state.annotation.points[0].world[0]',context),2);
pick([3,0,0]);assert.equal(count(),2);
vm.runInContext("handleInspectionMiss('no-surface')",context);assert.equal(get('inspection-hint').dataset.feedback,'miss');
vm.runInContext('restartMeasurement()',context);assert.equal(count(),0);assert.equal(step(),'ready');assert.equal(focused,1);assert.equal(get('inspection-restart').hidden,true);
assert.equal(get('inspection-hint').dataset.feedback,'normal','explicit restart clears persistent miss');
assert.equal(vm.runInContext('JSON.stringify(state.annotation.reference_uv)',context),'[0.2,0.3]');assert.equal(get('feedback-note').value,'User note 中文 stays exactly');
vm.runInContext("handleInspectionMiss('outside-view');toggleInspection('point')",context);assert.equal(step(),'point-ready');assert.equal(get('inspection-hint').dataset.feedback,'normal','tool switch clears persistent miss');
pick([0,0,0]);assert.equal(step(),'point-recorded');pick([4,0,0]);assert.equal(count(),1);assert.equal(vm.runInContext('state.annotation.points[0].world[0]',context),4);
vm.runInContext('state.previewBusy=true;renderInspection()',context);assert.equal(step(),'waiting');
vm.runInContext("state.previewBusy=false;state.review.status='submitted';renderInspection()",context);assert.equal(get('inspection-restart').hidden,true);assert.equal(get('inspection-hint').children.length,1,'read-only result gives no picking instruction');
context.testViewport.inspectionMeasurement=()=>({distance:1.25,display_distance:1.25,display_units:'preview_world_units',calibrated:false});
vm.runInContext("state.review.status='pending';state.inspectionTool='measure';state.annotation.points=[{object_id:'obj',local:[0,0,0],world:[0,0,0]},{object_id:'obj',local:[1.25,0,0],world:[1.25,0,0]}];renderInspection()",context);
for(const [language,unit] of [['en','preview units'],['zh-Hans','预览单位'],['zh-Hant','預覽單位']]) {locale=language;vm.runInContext('renderInspection()',context);assert.ok(hint().includes('1.25 '+unit));}
vm.runInContext("state.review.status='submitted';renderInspection();restartMeasurement()",context);assert.equal(count(),2);assert.equal(get('inspection-restart').hidden,true);assert.equal(get('inspection-hint').children.length,1);
for(const [inspector,notes] of [[false,false],[true,false],[true,true]]) {
 vm.runInContext("state.review.status='pending';state.inspectionTool='measure';clearSurfacePoints();setInspector("+inspector+")",context);
 get('feedback-details').open=notes;
 pick([0,0,0]);pick([1,0,0]);
 vm.runInContext("toggleInspection('point')",context);pick([2,0,0]);
 vm.runInContext("toggleInspection('point')",context);
 const panels=panelSnapshot();
 vm.runInContext("selectObject('obj')",context);
 assert.deepEqual(panelSnapshot(),panels,'ordinary object selection must preserve sidebar and note disclosure');
 assert.equal(get('feedback-note').value,'User note 中文 stays exactly');
}
const snapCalls=[];
context.testViewport.setInspectionSnap=enabled=>snapCalls.push(enabled);
vm.runInContext("state.inspectionTool='measure';clearSurfacePoints();renderInspection()",context);
assert.equal(get('inspection-snap').hidden,false);assert.equal(get('inspection-snap').attributes['aria-pressed'],'true','snap defaults enabled');
context.hoverSample={object_id:'obj',local:[1,2,3],world:[1,2,3],snap_kind:'vertex',kind:'vertex',reason:'ui-only'};
vm.runInContext('selectSurface(hoverSample)',context);
assert.equal(vm.runInContext('JSON.stringify(Object.keys(state.annotation.points[0]).sort())',context),'["local","object_id","world"]','snap metadata is excluded from persisted points');
context.hoverSample.world[0]=999;assert.equal(vm.runInContext('state.annotation.points[0].world[0]',context),1,'stored coordinates are copied');
const hoverState=vm.runInContext('JSON.stringify(state)',context),hoverPanels=panelSnapshot();
for(const language of ['en','zh-Hans','zh-Hant']) {
 locale=language;
 for(const kind of ['vertex','edge','surface']) {
  vm.runInContext("handleInspectionHover({kind:"+JSON.stringify(kind)+"})",context);
  assert.equal(get('inspection-candidate').textContent,messages[language]['review.inspection.candidate.'+kind]);
  assert.equal(get('inspection-candidate').hidden,false);
 }
 for(const reason of ['deformed','instanced','dense']) {
  vm.runInContext("handleInspectionHover({kind:'unavailable',reason:"+JSON.stringify(reason)+"})",context);
  assert.equal(get('inspection-candidate').title,messages[language]['review.inspection.snapUnavailable.'+reason]);
 }
}
assert.equal(vm.runInContext('JSON.stringify(state)',context),hoverState,'hover feedback does not change review data');assert.deepEqual(panelSnapshot(),hoverPanels);
vm.runInContext("handleInspectionHover({kind:'vertex'})",context);
const snapAnnotation=vm.runInContext('JSON.stringify(state.annotation)',context);
vm.runInContext('toggleInspectionSnap()',context);
assert.equal(get('inspection-snap').attributes['aria-pressed'],'false');assert.equal(snapCalls.at(-1),false);
assert.equal(get('inspection-candidate').textContent,messages[locale]['review.inspection.candidate.surface']);
assert.equal(vm.runInContext('JSON.stringify(state.annotation)',context),snapAnnotation,'snap toggle preserves point A');assert.deepEqual(panelSnapshot(),hoverPanels);
vm.runInContext('toggleInspectionSnap()',context);assert.equal(snapCalls.at(-1),true);assert.equal(get('inspection-snap').attributes['aria-pressed'],'true');
vm.runInContext("handleInspectionMiss('no-surface')",context);assert.equal(get('inspection-candidate').hidden,true);assert.equal(count(),1);
vm.runInContext("toggleInspection('measure')",context);assert.equal(get('inspection-snap').hidden,true);assert.equal(get('inspection-candidate').hidden,true);
console.log(JSON.stringify({status:'PASS',checks:'A/B progression, model and native preview units, stable live feedback, frozen receipt precedence, restart/note/evidence retention, unchanged panel disclosure, misses preserve A, snap defaults on and remains viewing state, vertex/edge/surface/unavailable hover feedback in three locales, no snap metadata persisted'}));
