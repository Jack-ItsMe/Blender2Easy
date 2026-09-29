
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {messages} from '../../skills/blender2easy/editor/web/locales/authoring.js';
const source=readFileSync(new URL('../../skills/blender2easy/editor/web/app.js',import.meta.url),'utf8')
 .replace(/\r\n/g,'\n')
 .replace(/^import .*;$/gm,'')
 .replace(/\ninitPreferences\(\);\ntranslatePage\(\);\nonLocaleChange\(refreshLanguage\);\ninit\(\);\s*$/, '');
const keys=Object.keys(messages.en).sort();
const tokens=value=>[...value.matchAll(/\{(\w+)\}/g)].map(match=>match[1]).sort();
for(const entries of Object.values(messages)){
 assert.deepEqual(Object.keys(entries).sort(),keys);
 for(const key of keys)assert.deepEqual(tokens(entries[key]),tokens(messages.en[key]),key);
}
let locale='en';const elements=new Map();
class Element {constructor(id=''){Object.assign(this,{id,dataset:{},value:'',checked:false,hidden:false,disabled:false,scrollTop:0,scrollLeft:0,isConnected:true,classList:{toggle(){}},children:[],attributes:{}})}setAttribute(k,v){this.attributes[k]=String(v)}removeAttribute(k){delete this.attributes[k]}querySelectorAll(){return []}querySelector(){return null}contains(){return false}addEventListener(){}replaceChildren(){this.innerHTML=''}showModal(){this.open=true}close(){this.open=false}focus(){document.activeElement=this}setSelectionRange(a,b,d){Object.assign(this,{selectionStart:a,selectionEnd:b,selectionDirection:d})}}
const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id)};
const document={getElementById:get,querySelectorAll:()=>[],querySelector:()=>get('title'),activeElement:null,title:''};
const context={messages,document,console,Intl,window:{confirm:()=>true},CSS:{escape:x=>x},localStorage:{},setTimeout:()=>0,clearTimeout(){},registerMessages(){},translatePage(){},t:(key,params={})=>(messages[locale][key]??key).replace(/\{(\w+)\}/g,(_,k)=>String(params[k])),formatNumber:(v,o={})=>new Intl.NumberFormat(locale,o).format(v),getLocale:()=>locale,localizeError:x=>x?.message??String(x??''),HTMLElement:Element,HTMLInputElement:Element,HTMLTextAreaElement:Element};
vm.createContext(context);vm.runInContext(source+';globalThis.a={state,renderAll,refreshLanguage,msg,showNew,showOpen,showAdd,showJson,showResults,preserveControls,status,errorText,number};',context);const a=context.a;
a.state.project={id:'scene-中文',units:'m',scene:{objects:[{id:'cube-中文',type:'cube',location:[1,2,3],rotation_deg:[0,0,0],scale:[1,1,1],dimensions:[1,1,1],material:'mat-中文'}],materials:[{id:'mat-中文',color:[.5,.4,.3,1]}],cameras:[{id:'cam-中文',type:'PERSP',location:[4,3,2],target:[0,0,0]}],lights:[],animation:[{target:'cube-中文',property:'location',keys:[{frame:1,value:[1,2,3]},{frame:48,value:[2,2,3]}]}]},shots:[{id:'shot-中文',title:'用户镜头名称',camera:'cam-中文',source_range:[1,48],timing:[{source_range:[1,48],frames:24,anchors:[1,48]}]}],render:{resolution:[1280,720],fps:24,samples:16,engine:'BLENDER_EEVEE'}};
const snapshot=JSON.stringify(a.state.project);a.state.saved=snapshot;a.state.selected='cube-中文';a.state.plan={sourceFrames:[1,10,20,48]};a.state.index=2;a.state.frame=20;
for(const lang of ['en','zh-Hans','zh-Hant','en']){locale=lang;for(const tab of ['object','material','camera','output']){a.state.tab=tab;a.renderAll();assert(!get('inspector').innerHTML.includes('authoring.'));}a.refreshLanguage();assert.equal(a.state.index,2);assert.equal(a.state.frame,20);assert.equal(JSON.stringify(a.state.project),snapshot);for(const show of [a.showNew,a.showOpen,()=>a.showOpen(true),a.showAdd,a.showJson]){show();a.refreshLanguage();assert(!get('dialog-content').innerHTML.includes('authoring.'));}assert(get('dialog-content').innerHTML.includes('用户镜头名称'));a.showResults([{video_url:'/video.mp4',previews_urls:['/preview.png'],check_url:'/report.json'}]);assert(get('results-content').innerHTML.includes('data-i18n-alt="authoring.renderPreviewAlt"'));}
a.status(a.msg('poseRecorded',{frame:20}));locale='zh-Hant';a.refreshLanguage();assert.equal(get('status-message').textContent,'已記錄第 20 影格的姿態');locale='en';let error;try{a.number('x')}catch(e){error=e}assert.equal(a.errorText(error),'Enter a finite number');locale='zh-Hant';assert.equal(a.errorText(error),'請輸入有效數字');
let fields=[new Element('draft'),new Element('checkbox')];Object.assign(fields[0],{value:'未提交 draft',selectionStart:2,selectionEnd:5,selectionDirection:'backward',scrollTop:11});fields[0].dataset.editing='true';fields[1].checked=true;document.activeElement=fields[0];const root={scrollTop:23,scrollLeft:2,querySelectorAll:()=>fields};a.preserveControls(root,()=>{fields=[new Element('draft'),new Element('checkbox')];root.scrollTop=0});assert.equal(fields[0].value,'未提交 draft');assert.equal(fields[0].selectionStart,2);assert.equal(fields[0].selectionEnd,5);assert.equal(fields[0].selectionDirection,'backward');assert.equal(fields[0].scrollTop,11);assert.equal(fields[1].checked,true);assert.equal(document.activeElement,fields[0]);assert.equal(root.scrollTop,23);
console.log('PASS: three-locale renderers; 305-key and placeholder parity; unchanged model and timeline; draft/focus/selection/scroll retention; lazy status and error translation');
