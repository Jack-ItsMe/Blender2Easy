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
