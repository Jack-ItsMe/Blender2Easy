import { Viewport } from './viewport.js';
import {registerMessages, t, formatNumber, getLocale, localizeError, initPreferences, translatePage, onLocaleChange} from './i18n.js';
import {messages} from './locales/authoring.js';

registerMessages(messages);
// Keep message descriptors until display time so in-flight status text follows locale changes.
const msg = (key, params={}) => ({key, params, toString:()=>t('authoring.'+key, params)});
const displayNumber = (value, options={}) => ({toString:()=>formatNumber(value, options)});
const textBindings = new Map();
function setText(element, value) { element.removeAttribute('data-i18n');textBindings.set(element,value);element.textContent=String(value??''); }
function uiError(value) { const error=new Error(String(value));error.uiMessage=value;return error; }
const localizedError = error => ({toString:()=>errorText(error)});
let viewportMessage=null, dialogContent=null, dialogError=null, translating=false;


const $ = (id) => document.getElementById(id);
const clone = (value) => JSON.parse(JSON.stringify(value));
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const state = {token:null,project:null,saved:'',path:'',revision:'',mode:'procedural',manifest:null,preview:null,projects:[],selected:null,tab:'object',material:null,camera:null,shot:0,frame:1,index:0,plan:null,history:[],future:[],job:null,saving:false,loading:false,playing:false,autoKey:false,viewCamera:'',epoch:0,planSeq:0,viewSeq:0,warnings:[]};
let viewport, toastTimer, recoveryTimer, planTimer, animationTime = 0, dialogHandler = null;
const propertyNames = {location:msg('position'),rotation_deg:msg('rotate'),scale:msg('scale')};
const typeNames = {cube:msg('cube'),cylinder:msg('cylinder'),sphere:msg('sphere'),empty:msg('empty'),MESH:msg('grid'),EMPTY:msg('empty'),CAMERA:msg('camera'),LIGHT:msg('light'),CURVE:msg('curve'),ARMATURE:msg('armature')};
const dirty = () => !!state.project && JSON.stringify(state.project) !== state.saved;
const native = () => state.mode === 'native';
const shot = () => state.project?.shots[state.shot] || state.project?.shots[0];
const objects = () => native() ? (state.manifest?.objects || []).filter(o=>!['CAMERA','LIGHT'].includes(o.type)) : (state.project?.scene?.objects || []);
const materials = () => native() ? (state.manifest?.materials || []) : (state.project?.scene?.materials || []);
const cameras = () => native() ? (state.manifest?.cameras || []) : (state.project?.scene?.cameras || []);
const lights = () => native() ? (state.manifest?.lights || []) : (state.project?.scene?.lights || []);
const findObject = (id) => objects().find(o => o.id === id);
const selectedObject = () => findObject(state.selected);
const findCamera = () => cameras().find(c => c.id === state.camera) || cameras().find(c => c.id === shot()?.camera) || cameras()[0];
const fps = () => state.project?.render?.fps || 24;
function errorText(error) { return String(error?.uiMessage || (error?.key?error:localizeError(error)) || msg('unknownError')); }
function shortMessage(value, limit=240) { const first=String(value??'').split(/\r?\n/).map(line=>line.trim()).find(Boolean)||String(msg('unknownError'));return first.length>limit?first.slice(0,limit-1)+'…':first; }
function hasErrorDetails(value) { const text=errorText(value);return text.includes('\n')||text.length>240; }
function status(text) { setText($('status-message'), {toString:()=>shortMessage(text)}); }
function toast(message, error=false) { clearTimeout(toastTimer); setText($('toast'), {toString:()=>shortMessage(message)}); $('toast').classList.toggle('error',error); $('toast').hidden=false; toastTimer=setTimeout(()=>$('toast').hidden=true,error?8000:3500); }
function showErrorDetails(error,open=false) {
  const full=errorText(error);$('results-toggle').hidden=false;setText($('results-toggle'),msg('errorDetails'));if(open)$('results-panel').hidden=false;
  setText($('result-meta'),msg('operationFailed'));
  $('results-content').innerHTML=`<p id="error-summary" class="error-text error-summary">${esc(shortMessage(full))}</p><details class="error-details"><summary><span data-i18n="authoring.expandError">${esc(msg('expandError'))}</span></summary><pre id="error-full-text" tabindex="0">${esc(full)}</pre><button id="copy-error-details" class="small"><span data-i18n="authoring.copyError">${esc(msg('copyError'))}</span></button></details><p class="help-text"><span data-i18n="authoring.errorHelp">${esc(msg('errorHelp'))}</span></p>`;
  setText($('error-summary'),{toString:()=>shortMessage(errorText(error))});setText($('error-full-text'),localizedError(error));
  $('copy-error-details').onclick=async()=>{try{await navigator.clipboard.writeText(errorText(error));toast(msg('errorCopied'));}catch{const range=document.createRange();range.selectNodeContents($('error-full-text'));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);toast(msg('copyFallback'));}};
}
function fail(error) { console.error(error);const message=localizedError(error);if(hasErrorDetails(error))showErrorDetails(error);toast(message,true);status(message); }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-Editor-Token':state.token},body:JSON.stringify(body)});
  let data; try {data = await response.json();} catch {throw uiError(msg('invalidResponse',{status:response.status}));}
  if (!response.ok) throw (data.error?new Error(data.error):uiError(msg('requestFailed',{status:response.status})));
  return data;
}
function guard(fn) { return (...args) => Promise.resolve().then(()=>fn(...args)).catch(fail); }
function uniqueId(prefix, entries) { let n=1; const used = new Set(entries.map(x=>x.id)); while(used.has(`${prefix}-${n}`))n++;return `${prefix}-${n}`; }
function number(value, min=-Infinity, max=Infinity) { const n=Number(value); if((typeof value==='string'&&!value.trim())||!Number.isFinite(n) || n<min || n>max)throw uiError(msg(Number.isFinite(min)?Number.isFinite(max)?'numberRange':'numberMin':Number.isFinite(max)?'numberMax':'validNumber',{min:displayNumber(min),max:displayNumber(max)}));return n; }
function options(entries, selected, label) {return entries.map(x=>`<option value="${esc(x.id)}" ${x.id===selected?'selected':''}>${esc(label?label(x):x.id)}</option>`).join('');}
function withOverride(kind, id) {
  state.project.source.overrides ||= {};state.project.source.overrides[kind] ||= [];
  let entry=state.project.source.overrides[kind].find(o=>o.id===id);
  if(!entry){entry={id};state.project.source.overrides[kind].push(entry);}return entry;
}
function effective(kind, item) {if(!item)return null;const override=native()?state.project.source.overrides?.[kind]?.find(o=>o.id===item.id):null;return {...item,...override};}
function recoveryKey(){return `object-animation:recovery:${state.path}`;}
function storeRecovery(){clearTimeout(recoveryTimer);recoveryTimer=setTimeout(()=>{try{if(dirty())localStorage.setItem(recoveryKey(),JSON.stringify({revision:state.revision,project:state.project,time:new Date().toISOString()}));else localStorage.removeItem(recoveryKey());}catch{}},300);}
function markStatus(){
  setText($('save-state'), state.saving?msg('saving'):dirty()?msg('unsaved'):msg('allSaved'));
  $('save-state').classList.toggle('dirty',dirty());
  $('undo-btn').disabled=!state.history.length || state.loading || state.saving;
  $('redo-btn').disabled=!state.future.length || state.loading || state.saving;
  $('save-btn').disabled=!state.project || state.saving || state.loading || !!state.job;
  for(const id of ['preview-btn','render-btn'])$(id).disabled=!state.project || !!state.job || state.loading || state.saving;
  for(const id of ['new-btn','open-btn','import-btn'])$(id).disabled=!!state.job || state.loading || state.saving;
  $('add-btn').disabled=native() || !state.project || state.loading;
  $('key-add').disabled=native() || !selectedObject() || !state.project;
  $('autokey-label').hidden=native();$('interpolation').hidden=native();$('key-add').hidden=native();
  document.querySelector('title').removeAttribute('data-i18n');document.title=`${dirty()?'● ':''}${state.project?.id || msg('brand')} · ${esc(msg('studio'))}`;
}
function snapshot(){return clone(state.project);}
function mutate(action, message=msg('changed'), {rebuild=true,replan=false}={}) {
  if(!state.project || state.loading || state.saving)return;
  const before=snapshot();try{action();}catch(error){state.project=before;fail(error);renderInspector();return;}
  if(JSON.stringify(before)===JSON.stringify(state.project))return;
  state.history.push(before);if(state.history.length>80)state.history.shift();state.future=[];
  markStatus();storeRecovery();status(message);renderHierarchy();renderInspector();renderTimeline();updateProjectLabels();
  if(rebuild)refreshViewport();if(replan)schedulePlan();
}
function undo(redo=false){if(state.saving || state.loading)return;const from=redo?state.future:state.history,to=redo?state.history:state.future;if(!from.length)return;to.push(snapshot());state.project=from.pop();state.shot=Math.min(state.shot,state.project.shots.length-1);renderAll();refreshViewport();schedulePlan();markStatus();storeRecovery();status(redo?msg('redone'):msg('undone'));}
function stop(){state.playing=false;$('play-btn').innerHTML=icon('play');$('play-btn').removeAttribute('data-i18n-aria-label');$('play-btn').setAttribute('aria-label',msg('play'));}
function discard(){if(!dirty())return true;return window.confirm(msg('discardConfirm'));}
async function acceptProject(data, {recover=true,preserve=false}={}) {
  $('results-panel').hidden=true;$('results-toggle').hidden=true;setText($('results-toggle'),msg('viewResults'));$('results-content').replaceChildren();setText($('result-meta'),'');
  state.projects=[{id:data.project.id,title:data.project.title||data.project.id,path:data.path},...state.projects.filter(project=>project.path!==data.path)];
  stop();state.epoch++;state.planSeq++;state.viewSeq++;state.plan=null;state.project=clone(data.project);state.saved=JSON.stringify(data.project);state.path=data.path;state.revision=data.revision;state.mode=data.mode || (data.project.source?'native':'procedural');state.preview=data.preview || null;state.manifest=data.manifest || data.preview?.manifest || null;state.warnings=data.warnings || [];state.history=[];state.future=[];state.shot=0;state.index=0;state.frame=shot()?.source_range?.[0] || 1;state.selected=null;state.material=null;state.camera=null;state.viewCamera='';
  if(recover){try{const saved=JSON.parse(localStorage.getItem(recoveryKey()) || 'null');if(saved && saved.revision===state.revision && JSON.stringify(saved.project)!==state.saved && window.confirm(msg('recoverConfirm',{date:{toString:()=>new Date(saved.time).toLocaleString(getLocale())}}))){state.project=saved.project;state.history.push(clone(data.project));}}catch{}}
  renderAll();markStatus();await refreshViewport(preserve);await loadPlan();
  if(native()&&!state.preview){showViewportMessage(msg('preparingScene'),msg('readingScene'));await startJob('native-preview');}
  else status(msg('projectLoaded'));
}
function updateProjectLabels(){
  if(!state.project)return;
  $('project-title').removeAttribute('data-i18n');setText($('project-title'),state.project.id);setText($('project-path'),state.path);$('project-path').title=state.path;$('mode-badge').removeAttribute('data-i18n');setText($('mode-badge'),native()?msg('nativeMode'):msg('proceduralMode'));
  const r=state.project.render;setText($('render-summary'),`${r.resolution.map(n=>formatNumber(n,{useGrouping:false})).join(' × ')} · ${formatNumber(r.fps,{useGrouping:false})} fps · ${r.engine==='CYCLES'?'Cycles':'EEVEE'}`);
  setText($('object-count'),displayNumber(objects().length));
  $('shot-select').innerHTML=state.project.shots.map((s,i)=>`<option value="${i}" ${i===state.shot?'selected':''}>${esc(s.title||s.id)}</option>`).join('');
  const desired=state.viewCamera;$('view-camera').innerHTML=`<option value="">${esc(msg('freeView'))}</option>`+options(cameras(),desired);$('view-camera').value=desired;
}
function renderAll(){updateProjectLabels();renderHierarchy();renderInspector();renderTimeline();markStatus();}
async function refreshViewport(preserveView=true){
  if(!viewport || !state.project)return;const serial=++state.viewSeq;
  try{await viewport.setProject(clone(state.project),{nativePreview:state.preview,preserveView});if(serial!==state.viewSeq)return;viewport.setFrame(state.frame);viewport.select(state.selected);viewport.setCamera(state.viewCamera||null);if(!native()||state.preview)$('viewport-message').hidden=true;renderInspector();}
  catch(e){if(serial!==state.viewSeq)return;showViewportMessage(msg('viewportFailed'),localizedError(e),msg('retry'),()=>refreshViewport());fail(e);}
}
function showViewportMessage(title, detail, action, handler){viewportMessage=[title,detail,action,handler];const detailed=hasErrorDetails(detail);$('viewport-message').innerHTML=`<strong>${esc(title)}</strong><p>${esc(shortMessage(detail))}</p>${action?`<button id="viewport-retry" class="primary">${esc(action)}</button>`:'<span class="spinner"></span>'}${detailed?`<button id="viewport-error-details" class="text-btn">${esc(msg('fullError'))}</button>`:''}`;$('viewport-message').hidden=false;if(action)$('viewport-retry').onclick=guard(handler);if(detailed)$('viewport-error-details').onclick=()=>showErrorDetails(detail,true);}
function renderHierarchy(){
  if(!state.project)return;const search=$('object-search').value.trim().toLowerCase();const all=objects();const animTargets=new Set((state.project.scene?.animation||[]).map(a=>a.target));
  function depth(o, seen=new Set()){if(!o.parent || seen.has(o.id))return 0;seen.add(o.id);const p=all.find(x=>x.id===o.parent);return p?Math.min(4,1+depth(p,seen)):0;}
  function rows(list,type){return list.filter(x=>x.id.toLowerCase().includes(search)).map(o=>`<button class="tree-row ${state.selected===o.id?'selected':''}" role="treeitem" aria-selected="${state.selected===o.id}" data-select="${esc(o.id)}" data-kind="${type}" style="padding-left:${8+(type==='object'?depth(o)*12:0)}px" title="${esc(o.id)}">${icon(type==='camera'?'camera':type==='light'?'light':'cube')}<span class="tree-name">${esc(o.id)}</span>${animTargets.has(o.id)?'<span class="tree-key">◆</span>':''}</button>`).join('');}
  let html=`<div class="tree-group"><span>${esc(msg('objectsGroup'))}</span><span>${formatNumber(all.length)}</span></div>${rows(all,'object')}`;
  html+=`<div class="tree-group"><span>${esc(msg('camerasGroup'))}</span><span>${formatNumber(cameras().length)}</span></div>${rows(cameras(),'camera')}`;
  html+=`<div class="tree-group"><span>${esc(msg('lightsGroup'))}</span><span>${formatNumber(lights().length)}</span></div>${rows(lights(),'light')}`;
  if(!all.length && !cameras().length)html+=`<p class="empty-tree">${esc(msg('sceneNotLoaded'))}</p>`;
  $('hierarchy').innerHTML=html;for(const row of $('hierarchy').querySelectorAll('[data-select]'))row.onclick=()=>select(row.dataset.select,row.dataset.kind);
}
function select(id,kind){state.selected=id;if(!kind)kind=cameras().some(c=>c.id===id)?'camera':lights().some(l=>l.id===id)?'light':'object';if(kind==='camera'){state.camera=id;state.tab='camera';}else state.tab='object';const obj=findObject(id);if(obj?.material)state.material=Array.isArray(obj.material)?obj.material[0]:obj.material;viewport?.select(id);renderHierarchy();renderInspector();renderTimeline();markStatus();}
const scalarField=(label,key,value,{min,max,step=0.01,disabled=false,integer=false}={})=>`<div class="field"><label for="p-${key}">${label}</label><input id="p-${key}" data-field="${key}" type="number" value="${esc(value)}" step="${integer?1:step}" ${min!==undefined?`min="${min}"`:''} ${max!==undefined?`max="${max}"`:''} ${disabled?'disabled':''}></div>`;
const textField=(label,key,value)=>`<div class="field block"><label for="p-${key}">${label}</label><input id="p-${key}" data-field="${key}" value="${esc(value)}"></div>`;
function vectorField(label,key,value,fallback=[0,0,0],disabled=false){const v=value||fallback;return `<div class="vector"><div class="vector-header"><span>${label}</span>${!disabled && propertyNames[key] && !native()?`<button class="tiny-key" data-key="${key}" aria-label="${esc(msg('addPropertyKey',{property:label}))}" title="${esc(msg('addPropertyKey',{property:label}))}">◇</button>`:''}</div><div class="vector-inputs">${['X','Y','Z'].map((axis,i)=>`<label class="axis-input"><span>${axis}</span><input type="number" aria-label="${label} ${axis}" data-vector="${key}" data-axis="${i}" value="${esc(Math.round(v[i]*10000)/10000)}" step="${key==='rotation_deg'?1:0.01}" ${disabled?'disabled':''}></label>`).join('')}</div></div>`;}
function section(title, content){return `<section class="property-section"><h3>${title}</h3>${content}</section>`;}
function currentTransform(o){try{return viewport?.getTransform?.(o.id) || effective('objects',o);}catch{return effective('objects',o);}}
function renderInspector(){
  const focused=$('inspector').contains(document.activeElement)?document.activeElement:null;
  const focusSelector=focused?.id?`#${CSS.escape(focused.id)}`:focused?.dataset.vector?`[data-vector="${CSS.escape(focused.dataset.vector)}"][data-axis="${focused.dataset.axis}"]`:focused?.dataset.field?`[data-field="${CSS.escape(focused.dataset.field)}"]`:focused?.dataset.phase?`[data-phase="${focused.dataset.phase}"]`:null;
  const caret=focused?.type==='text'?[focused.selectionStart,focused.selectionEnd]:null;
  const focusDraft=focused?.dataset.editing==='true'?focused.value:null;
  for(const t of document.querySelectorAll('[data-tab]')){t.classList.toggle('active',t.dataset.tab===state.tab);t.setAttribute('aria-selected',t.dataset.tab===state.tab);}
  if(!state.project){$('inspector').innerHTML='';return;}
  const panel=$('inspector');let html='';
  if(state.tab==='object'){
    const light=lights().find(l=>l.id===state.selected);const o=selectedObject();
    if(light && !o){html=lightInspector(light);} else if(!o){html=`<div class="empty-inspector">${icon('cube')}<h3>${esc(msg('selectObject'))}</h3><p>${esc(msg('selectObjectHelp'))}<br>${esc(msg('selectObjectHelpMore'))}</p>${!native()?`<button id="empty-add" class="section-action">${esc(msg('addFirstObject'))}</button>`:''}</div>`;}
    else {
      const item=effective('objects',o);const transform=currentTransform(item);const locked=native()&&item.editable_transform===false;
      html=`<div class="inspector-title">${icon('cube')}<span>${esc(item.id)}</span></div><p class="inspector-subtitle">${esc(typeNames[item.type]||item.type)}${item.parent?esc(msg('parentCaption',{parent:item.parent})):msg('rootCaption')}</p>`;
      if(locked)html+=`<div class="warning-strip">${esc((item.transform_warning?localizeError(item.transform_warning):msg('transformReadOnly')))}</div>`;
      html+=section(`${esc(msg('transform'))} <span class="muted">${native()?msg('localOverrides'):state.autoKey?msg('keyCurrentFrame'):msg('keyAnimatedProperties')}</span>`,vectorField(msg('positionUnits',{unit:native()?msg('nativeUnits'):state.project.units||'m'}),'location',transform.location,[0,0,0],locked)+vectorField(msg('rotationDegrees'),'rotation_deg',transform.rotation_deg,[0,0,0],locked)+vectorField(msg('scale'),'scale',transform.scale,[1,1,1],locked));
      if(item.type!=='empty' && item.type!=='EMPTY')html+=section(msg('geometry'),vectorField(msg('localDimensions',{unit:native()?msg('nativeUnits'):state.project.units||'m'}),'dimensions',item.dimensions,[1,1,1],native())+(!native()?scalarField(msg('bevel'),'bevel',item.bevel||0,{min:0,step:.005}):`<p class="help-text">${esc(msg('nativeGeometryHelp'))}</p>`));
      if(!native())html+=section(msg('relations'),`<div class="field"><label>${esc(msg('material'))}</label><select aria-label="${esc(msg('material'))}" data-field="material"><option value="">${esc(msg('defaultMaterial'))}</option>${options(materials(),item.material)}</select></div><div class="field"><label>${esc(msg('parent'))}</label><select aria-label="${esc(msg('parent'))}" data-field="parent"><option value="">${esc(msg('sceneRoot'))}</option>${options(objects().filter(x=>x.id!==item.id&&!isDescendant(x,item.id)),item.parent)}</select></div>`);
      const tracks=(state.project.scene?.animation||[]).filter(t=>t.target===item.id);
      if(!native())html+=section(msg('animationTracks'),tracks.length?tracks.map(t=>`<div class="track-item"><span>◆ ${propertyNames[t.property]}</span><span class="muted">${esc(msg('keyCount',{count:displayNumber(t.keys.length)}))}</span><button data-track-delete="${t.property}" aria-label="${esc(msg('deleteTrackLabel',{property:propertyNames[t.property]}))}" title="${esc(msg('deleteTrackLabel',{property:propertyNames[t.property]}))}">×</button></div>`).join('')+`<button id="delete-current-keys" class="wide quiet small">${esc(msg('deleteCurrentKeys'))}</button>`:`<p class="help-text">${esc(msg('animationHelp'))}</p>`);
      if(native())html+=`<p class="help-text warning">${esc(msg('nativeOverrideHelp'))}</p><button id="reset-object" class="wide quiet small">${esc(msg('clearObjectOverride'))}</button>`;
      else html+=`<button id="delete-object" class="danger-link section-action">${esc(msg('deleteObjectChildren'))}</button>`;
    }
  } else if(state.tab==='material')html=materialInspector();
  else if(state.tab==='camera')html=cameraInspector();
  else html=outputInspector();
  panel.innerHTML=html;bindInspector();
  if(focusSelector){const replacement=panel.querySelector(focusSelector);if(replacement&&!replacement.disabled){if(focusDraft!==null){replacement.value=focusDraft;replacement.dataset.editing='true';}replacement.focus({preventScroll:true});if(caret)try{replacement.setSelectionRange(...caret);}catch{}}}
}
function isDescendant(item,id){const visited=new Set();while(item?.parent&&!visited.has(item.id)){visited.add(item.id);if(item.parent===id)return true;item=findObject(item.parent);}return false;}
function lightInspector(light){const locked=native();return `<div class="inspector-title">${icon('light')}${esc(light.id)}</div><p class="inspector-subtitle">${esc(light.type)} · ${esc(msg('sceneLight'))}</p>${vectorField(msg('position'),'light-location',light.location,[0,0,0],locked)}${vectorField(msg('aimTarget'),'light-target',light.target,[0,0,0],locked)}${scalarField(msg('power'),'energy',light.energy||0,{min:0,step:10,disabled:locked})}${scalarField(msg('size'),'size',light.size||1,{min:.001,disabled:locked})}${locked?`<p class="help-text">${esc(msg('nativeLightHelp'))}</p>`:''}`;}
function materialInspector(){
  const list=materials();let item=list.find(m=>m.id===state.material)||list[0];if(!item)return `<div class="empty-inspector">${icon('cube')}<h3>${esc(msg('noMaterials'))}</h3>${!native()?`<button id="material-add" class="section-action">${esc(msg('createMaterial'))}</button>`:''}</div>`;
  state.material=item.id;item=effective('materials',item);const color=item.color||[.7,.7,.7,1],hex=colorToHex(color);const canEdit=key=>!native()||!item.editable_properties||item.editable_properties.includes(key);
  let html=`<div class="inspector-title">${esc(msg('surfaceMaterial'))}</div><p class="inspector-subtitle">${esc(msg('materialHelp'))}</p><div class="field block"><label>${esc(msg('material'))}</label><select aria-label="${esc(msg('material'))}" id="material-select">${options(list,item.id)}</select></div><div class="swatches">${list.map(m=>`<button class="swatch ${m.id===item.id?'selected':''}" data-material="${esc(m.id)}" style="background:${colorToHex(effective('materials',m).color||[.7,.7,.7,1])}" title="${esc(m.id)}" aria-label="${esc(m.id)}"></button>`).join('')}</div>`;
  html+=section(msg('surface'),`<div class="field"><label for="material-color">${esc(msg('baseColor'))}</label><div class="color-row"><span class="color-value">${hex.toUpperCase()}</span><input id="material-color" type="color" value="${hex}" aria-label="${esc(msg('baseColor'))}" ${canEdit('color')?'':'disabled'}></div></div>`+scalarField(msg('opacity'),'alpha',color[3]??1,{min:0,max:1,step:.05,disabled:!canEdit('color')})+scalarField(msg('roughness'),'roughness',item.roughness??.5,{min:0,max:1,step:.05,disabled:!canEdit('roughness')})+scalarField(msg('metallic'),'metallic',item.metallic??0,{min:0,max:1,step:.05,disabled:!canEdit('metallic')}));
  if(item.warnings?.length)html+='<div class="warning-strip">'+item.warnings.map(value=>esc(localizeError(value))).join('<br>')+'</div>';
  html+=native()?`<p class="help-text warning">${esc(msg('nativeMaterialHelp'))}</p><button id="reset-material" class="section-action quiet">${esc(msg('clearMaterialOverride'))}</button>`:'<button id="material-assign" class="section-action" '+(!selectedObject()?'disabled':'')+`>${esc(msg('assignMaterial'))}</button><button id="material-add" class="section-action quiet">${esc(msg('newMaterial'))}</button>`;
  return html;
}
function cameraInspector(){
  const base=findCamera();if(!base)return `<div class="empty-inspector"><h3>${esc(msg('noCameras'))}</h3></div>`;state.camera=base.id;const c=effective('cameras',base);const locked=native()&&c.editable_transform===false;
  let html=`<div class="inspector-title">${icon('camera')}${esc(msg('shotCamera'))}</div><p class="inspector-subtitle">${esc(msg('cameraHelp'))}</p><div class="field block"><label>${esc(msg('camera'))}</label><select aria-label="${esc(msg('camera'))}" id="camera-select">${options(cameras(),c.id)}</select></div>`;
  if(locked)html+=`<div class="warning-strip">${esc((c.transform_warning?localizeError(c.transform_warning):msg('cameraReadOnly')))}</div>`;
  html+=section(msg('positionOrientation'),vectorField(msg('position'),'camera-location',c.location,[0,0,0],locked)+vectorField(msg('target'),'camera-target',c.target,[0,0,0],locked)+`<button id="camera-from-view" class="wide small" ${locked?'disabled':''}>${esc(msg('useFreeView'))}</button>`);
  html+=section(msg('shot'),`<div class="field"><label>${esc(msg('projection'))}</label><select aria-label="${esc(msg('projection'))}" data-field="camera-type" ${native()?'disabled':''}><option value="PERSP" ${c.type==='PERSP'?'selected':''}>${esc(msg('perspective'))}</option><option value="ORTHO" ${c.type==='ORTHO'?'selected':''}>${esc(msg('orthographic'))}</option></select></div>`+scalarField(msg('focalLength'),'lens',c.lens||50,{min:1,max:1000,step:1})+scalarField(msg('orthoScale'),'ortho_scale',c.ortho_scale||5,{min:.001,step:.1})+`<button id="camera-look" class="section-action">${esc(msg('lookThrough'))}</button><button id="camera-use" class="section-action quiet">${esc(msg('useShotCamera'))}</button>`);
  html+=native()?`<button id="reset-camera" class="section-action quiet">${esc(msg('clearCameraOverride'))}</button>`:`<button id="camera-add" class="section-action quiet">${esc(msg('createCameraView'))}</button>`;
  return html;
}
function outputInspector(){
  const s=shot(),r=state.project.render;
  let html=`<div class="inspector-title">${esc(msg('shotOutput'))}</div><p class="inspector-subtitle">${esc(msg('currentShotId',{id:s.id}))}</p>`+textField(msg('shotName'),'shot-title',s.title||s.id)+`<div class="field"><label>${esc(msg('renderCamera'))}</label><select aria-label="${esc(msg('renderCamera'))}" data-field="shot-camera">${options(cameras(),s.camera)}</select></div>`;
  html+=section(msg('sourceRange'),`<div class="vector-inputs" style="grid-template-columns:1fr 1fr"><label class="field block"><span class="muted">${esc(msg('startFrame'))}</span><input id="range-start" type="number" value="${s.source_range[0]}" step="1"></label><label class="field block"><span class="muted">${esc(msg('endFrame'))}</span><input id="range-end" type="number" value="${s.source_range[1]}" step="1"></label></div><button id="apply-range" class="wide small">${esc(msg('applyRange'))}</button><p class="help-text">${esc(msg('rangeHelp'))}</p>`);
  const phases=s.timing?.length?s.timing:[{source_range:s.source_range,frames:s.source_range[1]-s.source_range[0]+1,anchors:[]}];
  html+=section(msg('timingDuration'),phases.map((p,i)=>`<div class="timing-phase"><span class="muted">${esc(msg('phaseCaption',{index:formatNumber(i+1,{minimumIntegerDigits:2,useGrouping:false}),range:p.source_range.map(n=>formatNumber(n,{useGrouping:false})).join('—')}))}</span><div class="field"><label>${esc(msg('outputFrames'))}</label><input aria-label="${esc(msg('outputFrames'))}" data-phase="${i}" type="number" min="${Math.max(1,new Set([p.source_range[0],...(p.anchors||[]),p.source_range[1]]).size)}" step="1" value="${p.frames}"></div><p class="help-text">${esc(msg('phaseDuration',{seconds:displayNumber(p.frames/r.fps,{minimumFractionDigits:2,maximumFractionDigits:2}),count:displayNumber(new Set([p.source_range[0],...(p.anchors||[]),p.source_range[1]]).size)}))}</p></div>`).join(''));
  html+=section(msg('render'),`<div class="field"><label>${esc(msg('resolutionPreset'))}</label><select aria-label="${esc(msg('resolutionPreset'))}" id="resolution-preset"><option value="">${esc(msg('custom'))}</option>${[[640,360],[1280,720],[1920,1080],[1080,1080],[1080,1920]].map(a=>`<option value="${a}" ${a.join()===r.resolution.join()?'selected':''}>${a.join(' × ')}</option>`).join('')}</select></div>`+scalarField(msg('width'),'width',r.resolution[0],{min:16,max:8192,step:2,integer:true})+scalarField(msg('height'),'height',r.resolution[1],{min:16,max:8192,step:2,integer:true})+scalarField(msg('frameRate'),'fps',r.fps,{min:1,max:120,step:1,integer:true})+scalarField(msg('samples'),'samples',r.samples,{min:1,max:4096,step:1,integer:true})+`<div class="field"><label>${esc(msg('engine'))}</label><select aria-label="${esc(msg('engine'))}" data-field="engine"><option value="BLENDER_EEVEE" ${r.engine==='BLENDER_EEVEE'?'selected':''}>EEVEE</option><option value="CYCLES" ${r.engine==='CYCLES'?'selected':''}>Cycles</option></select></div><div class="field"><label>${esc(msg('transparentPng'))}</label><input aria-label="${esc(msg('transparentPng'))}" type="checkbox" data-field="transparent" ${r.transparent?'checked':''}></div>`);
  html+=`<button id="advanced-json" class="section-action quiet">${esc(msg('advancedJson'))}</button>`;
  if(state.project.shots.length>1)html+=`<button id="delete-shot" class="section-action danger-link">${esc(msg('deleteShot'))}</button>`;
  if(state.warnings.length)html+='<p class="help-text warning">'+state.warnings.map(value=>esc(localizeError(value))).join('<br>')+'</p>';
  return html;
}
function colorToHex(color){return '#'+color.slice(0,3).map(v=>Math.round(Math.min(1,Math.max(0,v))*255).toString(16).padStart(2,'0')).join('');}
function addKey(target,property,value){
  state.project.scene.animation ||= [];let track=state.project.scene.animation.find(a=>a.target===target&&a.property===property);
  if(!track){track={target,property,keys:[]};state.project.scene.animation.push(track);}
  let key=track.keys.find(k=>k.frame===state.frame);if(!key){key={frame:state.frame,value:clone(value),interpolation:$('interpolation').value};track.keys.push(key);track.keys.sort((a,b)=>a.frame-b.frame);}else{key.value=clone(value);key.interpolation=$('interpolation').value;}
}
function updateTransform(id, values){
  const item=findObject(id);if(!item)return;
  if(native()&&item.editable_transform===false){toast((item.transform_warning?localizedError(item.transform_warning):msg('transformNotEditable')),true);return;}
  mutate(()=>{
    const dest=native()?withOverride('objects',id):state.project.scene.objects.find(o=>o.id===id);
    for(const [key,value] of Object.entries(values)){
      if(value.some(v=>!Number.isFinite(v)))throw uiError(msg('transformNumbers'));
      if(key==='scale'&&value.some(v=>v===0))throw uiError(msg('nonzeroScale'));
      if(!native()&&(state.autoKey||state.project.scene.animation?.some(t=>t.target===id&&t.property===key)))addKey(id,key,value);else dest[key]=clone(value);
    }
  },native()?msg('overrideUpdated'):msg('transformUpdated'));
}
function bindInspector(){
  for(const input of $('inspector').querySelectorAll('[data-vector]'))input.onchange=()=>{
    const name=input.dataset.vector,axis=Number(input.dataset.axis);let value;try{value=number(input.value);}catch(e){fail(e);renderInspector();return;}
    if(['location','rotation_deg','scale'].includes(name)){
      const item=selectedObject();if(!item)return;const v=clone(currentTransform(item)[name]||(name==='scale'?[1,1,1]:[0,0,0]));v[axis]=value;updateTransform(item.id,{[name]:v});
    }else mutate(()=>{
      let target,key=name;
      if(name.startsWith('camera-')){key=name.slice(7);const c=findCamera();target=native()?withOverride('cameras',c.id):state.project.scene.cameras.find(x=>x.id===c.id);target[key]=clone(effective('cameras',c)[key]||[0,0,0]);}
      else if(name.startsWith('light-')){key=name.slice(6);target=state.project.scene.lights.find(l=>l.id===state.selected);target[key]=clone(target[key]||[0,0,0]);}
      else{target=state.project.scene.objects.find(o=>o.id===state.selected);target[key]=clone(target[key]||[1,1,1]);if(name==='dimensions'&&value<=0)throw uiError(msg('positiveDimensions'));}
      target[key][axis]=value;
    });
  };
  for(const input of $('inspector').querySelectorAll('[data-field]'))input.onchange=()=>setField(input.dataset.field,input.type==='checkbox'?input.checked:input.value);
  for(const button of $('inspector').querySelectorAll('[data-key]'))button.onclick=()=>{const o=selectedObject();const p=button.dataset.key;mutate(()=>addKey(o.id,p,currentTransform(o)[p]||(p==='scale'?[1,1,1]:[0,0,0])),msg('keyAdded',{frame:displayNumber(state.frame),property:propertyNames[p]}));};
  for(const button of $('inspector').querySelectorAll('[data-track-delete]'))button.onclick=()=>{if(confirm(msg('deleteTrackConfirm')))mutate(()=>{state.project.scene.animation=state.project.scene.animation.filter(t=>!(t.target===state.selected&&t.property===button.dataset.trackDelete));},msg('trackDeleted'));};
  bind('empty-add',showAdd);bind('material-add',addMaterial);bind('camera-add',addCamera);bind('advanced-json',showJson);
  bind('delete-object',()=>{const id=state.selected;const ids=new Set(objects().filter(o=>o.id===id||isDescendant(o,id)).map(o=>o.id));if(confirm(msg('deleteObjectsConfirm',{count:displayNumber(ids.size)})))mutate(()=>{state.project.scene.objects=objects().filter(o=>!ids.has(o.id));state.project.scene.animation=(state.project.scene.animation||[]).filter(a=>!ids.has(a.target));state.selected=null;},msg('objectsDeleted'));});
  bind('delete-current-keys',()=>mutate(()=>{state.project.scene.animation=state.project.scene.animation.map(t=>t.target===state.selected?{...t,keys:t.keys.filter(k=>k.frame!==state.frame)}:t).filter(t=>t.keys.length);},msg('keysDeleted')));
  bind('material-select',(e)=>{state.material=e.target.value;renderInspector();},'change');
  for(const b of $('inspector').querySelectorAll('[data-material]'))b.onclick=()=>{state.material=b.dataset.material;renderInspector();};
  bind('material-color',e=>mutate(()=>{const hex=e.target.value;const base=materials().find(m=>m.id===state.material);const target=native()?withOverride('materials',state.material):base;target.color=[parseInt(hex.slice(1,3),16)/255,parseInt(hex.slice(3,5),16)/255,parseInt(hex.slice(5,7),16)/255,effective('materials',base).color?.[3]??1];},msg('colorUpdated')),'change');
  bind('material-assign',()=>mutate(()=>{state.project.scene.objects.find(o=>o.id===state.selected).material=state.material;},msg('materialAssigned')));
  bind('camera-select',e=>{state.camera=e.target.value;state.selected=e.target.value;viewport?.select(state.selected);renderHierarchy();renderInspector();},'change');
  bind('camera-look',()=>{state.viewCamera=findCamera().id;viewport?.setCamera(state.viewCamera);updateProjectLabels();});
  bind('camera-use',()=>mutate(()=>{shot().camera=findCamera().id;},msg('shotCameraSet'),{rebuild:false,replan:true}));
  bind('camera-from-view',()=>{const v=viewport.getView();mutate(()=>{const c=findCamera();const dest=native()?withOverride('cameras',c.id):c;Object.assign(dest,{location:v.location,target:v.target});},msg('cameraFromView'));});
  bind('apply-range',()=>{const a=Number($('range-start').value),b=Number($('range-end').value);mutate(()=>{if(!Number.isInteger(a)||!Number.isInteger(b)||b<a||a<1||b>1000000)throw uiError(msg('validFrameRange'));shot().source_range=[a,b];shot().timing=[{source_range:[a,b],frames:b-a+1,anchors:a===b?[a]:[a,b]}];state.index=0;state.frame=a;},msg('rangeReset'),{replan:true});});
  for(const input of $('inspector').querySelectorAll('[data-phase]'))input.onchange=()=>mutate(()=>{const s=shot();s.timing ||= [{source_range:clone(s.source_range),frames:s.source_range[1]-s.source_range[0]+1,anchors:[]}];const val=number(input.value,Number(input.min),1000000);if(!Number.isInteger(val))throw uiError(msg('integerFrames'));s.timing[Number(input.dataset.phase)].frames=val;},msg('durationUpdated'),{rebuild:false,replan:true});
  bind('resolution-preset',e=>{if(e.target.value)mutate(()=>{state.project.render.resolution=e.target.value.split(',').map(Number);},msg('resolutionUpdated'));},'change');
  bind('delete-shot',()=>{if(confirm(msg('deleteShotConfirm')))mutate(()=>{state.project.shots.splice(state.shot,1);state.shot=Math.max(0,state.shot-1);},msg('shotDeleted'),{rebuild:false,replan:true});});
  for(const kind of ['object','material','camera'])bind(`reset-${kind}`,()=>mutate(()=>{const category={object:'objects',material:'materials',camera:'cameras'}[kind],id=kind==='object'?state.selected:kind==='material'?state.material:findCamera().id;const list=state.project.source.overrides?.[category];if(list)state.project.source.overrides[category]=list.filter(x=>x.id!==id);},msg('overridesCleared')));
}
function bind(id,fn,event='click'){const element=$(id);if(element)element.addEventListener(event,guard(fn));}
function setField(name,raw){
  mutate(()=>{
    const s=shot(),r=state.project.render;
    if(name==='shot-title'){s.title=raw.trim()||s.id;return;}if(name==='shot-camera'){s.camera=raw;return;}
    if(['width','height','fps','samples'].includes(name)){const limit=['width','height'].includes(name)?[16,8192]:name==='fps'?[1,120]:[1,4096];const val=number(raw,...limit);if(!Number.isInteger(val))throw uiError(msg('integerParameter'));if(['width','height'].includes(name)){if(val%2!==0)throw uiError(msg('evenResolution'));r.resolution[name==='width'?0:1]=val;}else r[name]=val;return;}
    if(name==='engine'||name==='transparent'){r[name]=raw;return;}
    if(['roughness','metallic','alpha'].includes(name)){const val=number(raw,0,1),base=materials().find(m=>m.id===state.material),dest=native()?withOverride('materials',base.id):base;if(name==='alpha'){dest.color=clone(effective('materials',base).color||[.7,.7,.7,1]);dest.color[3]=val;}else dest[name]=val;return;}
    if(['camera-type','lens','ortho_scale'].includes(name)){const c=findCamera(),dest=native()?withOverride('cameras',c.id):c;if(name==='camera-type')dest.type=raw;else dest[name]=number(raw,.001);return;}
    const light=state.project.scene?.lights?.find(l=>l.id===state.selected);if(light&&['energy','size'].includes(name)){light[name]=number(raw,0);return;}
    const obj=state.project.scene.objects.find(o=>o.id===state.selected);if(name==='bevel'){obj.bevel=number(raw,0);return;}if(name==='material'||name==='parent'){if(raw)obj[name]=raw;else delete obj[name];}
  },msg('parameterUpdated'),{replan:['fps','shot-camera'].includes(name)});
}
function addMaterial(){mutate(()=>{const id=uniqueId('material',materials());state.project.scene.materials.push({id,color:[.6,.65,.68,1],roughness:.4,metallic:0});state.material=id;state.tab='material';},msg('materialCreated'));}
function addCamera(){if(native())return;const v=viewport.getView();mutate(()=>{const id=uniqueId('camera',cameras());state.project.scene.cameras.push({id,type:'PERSP',location:v.location,target:v.target,lens:50,ortho_scale:5});state.camera=id;state.selected=id;state.tab='camera';},msg('cameraCreated'));}
function addObject(type){
  mutate(()=>{const id=uniqueId(type,objects());const obj={id,type,location:[0,0,.5],rotation_deg:[0,0,0],scale:[1,1,1]};if(type!=='empty'){obj.dimensions=[1,1,1];if(materials()[0])obj.material=materials()[0].id;if(type==='cube')obj.bevel=.03;}state.project.scene.objects.push(obj);state.selected=id;state.tab='object';},msg('objectAdded',{type:typeNames[type]}));$('workspace-dialog').close();
}
function renderTimeline(){
  if(!state.project)return;const s=shot(),frames=state.plan?.sourceFrames || [];const total=frames.length || (s.timing?.reduce((n,p)=>n+p.frames,0) || s.source_range[1]-s.source_range[0]+1);
  $('timeline').max=Math.max(0,total-1);$('timeline').value=Math.min(state.index,total-1);setText($('frame-display'),formatNumber(state.frame,{minimumIntegerDigits:3,useGrouping:false}));setText($('output-frame-display'),frames.length&&frames[state.index]!==state.frame?msg('unsampledFrame'):msg('outputProgress',{index:displayNumber(Math.min(state.index+1,total)),total:displayNumber(total)}));setText($('shot-duration'),msg('seconds',{seconds:displayNumber(total/fps(),{minimumFractionDigits:2,maximumFractionDigits:2})}));
  $('timeline-ruler').innerHTML=Array.from({length:7},(_,i)=>`<span>${formatNumber(Math.round((total-1)*i/6)+1,{useGrouping:false})}</span>`).join('');
  globalThis.ObjectAnimationInteractions?.refreshRanges($('timeline'));
  const tracks=(state.project.scene?.animation||[]).filter(t=>t.target===state.selected);const keys=[...new Set(tracks.flatMap(t=>t.keys.map(k=>k.frame)))].filter(f=>f>=s.source_range[0]&&f<=s.source_range[1]);
  setText($('timeline-selection'),state.selected?`${state.selected}${keys.length?msg('keyPoses',{count:displayNumber(keys.length)}):native()?msg('nativeAnimation'):msg('noKeys')}`:msg('selectForKeys'));
  $('key-markers').innerHTML=keys.map(frame=>{const index=frames.indexOf(frame);const pos=index<0?(frame-s.source_range[0])/Math.max(1,s.source_range[1]-s.source_range[0]):index/Math.max(1,total-1);return `<button class="key-marker ${frame===state.frame?'active':''}" style="left:${Math.min(100,Math.max(0,pos*100))}%" data-frame="${frame}" title="${esc(msg('sourceFrameNumber',{frame:displayNumber(frame)}))}" aria-label="${esc(msg('jumpSourceFrame',{frame:displayNumber(frame)}))}"></button>`;}).join('');
  for(const marker of $('key-markers').querySelectorAll('[data-frame]'))marker.onclick=()=>{stop();const nativeFrame=Number(marker.dataset.frame),idx=frames.indexOf(nativeFrame);if(idx>=0)setIndex(idx);else{state.frame=nativeFrame;viewport?.setFrame(nativeFrame);renderTimeline();renderInspector();}};
}
function schedulePlan(){clearTimeout(planTimer);planTimer=setTimeout(()=>loadPlan().catch(fail),250);}
async function loadPlan(){
  if(!state.project)return;const seq=++state.planSeq,epoch=state.epoch;const result=await api('/api/plan',{project:state.project,shot:shot().id,path:state.path});if(seq!==state.planSeq||epoch!==state.epoch)return;state.plan=result;state.index=Math.min(state.index,Math.max(0,result.sourceFrames.length-1));setIndex(state.index);renderTimeline();
}
function setIndex(index,{inspector=true}={}){const frames=state.plan?.sourceFrames;if(!frames?.length)return;state.index=Math.max(0,Math.min(frames.length-1,Math.round(index)));state.frame=frames[state.index];viewport?.setFrame(state.frame);$('timeline').value=state.index;globalThis.ObjectAnimationInteractions?.refreshRanges($('timeline'));setText($('frame-display'),formatNumber(state.frame,{minimumIntegerDigits:3,useGrouping:false}));setText($('output-frame-display'),msg('outputProgress',{index:displayNumber(state.index+1),total:displayNumber(frames.length)}));for(const marker of $('key-markers').children)marker.classList.toggle('active',Number(marker.dataset.frame)===state.frame);if(inspector&&!$('inspector').contains(document.activeElement))renderInspector();}
function animate(now){requestAnimationFrame(animate);if(!state.playing||!state.plan?.sourceFrames?.length){animationTime=now;return;}const interval=1000/fps(),elapsed=now-animationTime;if(elapsed>=interval){const steps=Math.max(1,Math.floor(elapsed/interval));animationTime=now-(elapsed%interval);setIndex((state.index+steps)%state.plan.sourceFrames.length,{inspector:false});}}
async function saveProject(){
  if(state.saving)throw uiError(msg('waitSaving'));if(state.job)throw uiError(msg('waitJobSave'));if(!state.project)return;
  state.saving=true;markStatus();const epoch=state.epoch;const candidate=clone(state.project);
  try{const data=await api('/api/save',{project:candidate,revision:state.revision,path:state.path});if(epoch!==state.epoch)return;state.project=clone(data.project);state.saved=JSON.stringify(data.project);state.revision=data.revision;state.path=data.path;if('manifest' in data)state.manifest=data.manifest;else state.manifest=data.preview?.manifest||state.manifest;if('preview' in data)state.preview=data.preview;state.warnings=data.warnings||[];try{localStorage.removeItem(recoveryKey());}catch{}status(msg('savedLocal'));renderAll();await refreshViewport();if(native()&&!state.preview)showViewportMessage(msg('nativePreviewStale'),msg('nativePreviewStaleHelp'),msg('updateNativePreview'),()=>startJob('native-preview'));return data;}finally{state.saving=false;markStatus();}
}
async function startJob(operation){
  if(state.job){toast(msg('jobInProgress'));return;}if(!state.project)return;stop();
  const requestedSourceFrame=state.frame;
  if(dirty())await saveProject();
  if(operation==='preview'){
    await loadPlan();
    if(state.plan.sourceFrames[state.index]!==requestedSourceFrame){const mapped=state.plan.sourceFrames.indexOf(requestedSourceFrame);if(mapped<0)throw uiError(msg('sourceNotSampled',{frame:displayNumber(requestedSourceFrame)}));setIndex(mapped);}
  }
  const epoch=state.epoch,payload={operation,revision:state.revision,path:state.path};if(operation!=='native-preview')payload.shot=shot().id;if(operation==='preview')payload.frames=[state.index+1];
  const job=await api('/api/job',payload);state.job={...job,operation,epoch,revision:state.revision};markStatus();
  const label=operation==='run'?msg('shotRenderJob'):operation==='preview'?msg('framePreviewJob'):msg('nativeExportJob');status(msg('jobRunning',{operation:label}));
  if(operation!=='native-preview'){$('results-panel').hidden=false;$('results-toggle').hidden=false;setText($('results-toggle'),msg('viewResults'));setText($('result-meta'),operation==='preview'?msg('sourceFrameNumber',{frame:displayNumber(state.frame)}):shot().title||shot().id);$('results-content').innerHTML=`<div class="job-indicator"><span class="spinner"></span><span id="job-wait-text">${esc(msg('jobWait',{operation:label}))}</span></div><p class="help-text"><span data-i18n="authoring.jobVersionHelp">${esc(msg('jobVersionHelp'))}</span></p>`;}
  if($('job-wait-text'))setText($('job-wait-text'),msg('jobWait',{operation:label}));
  pollJob(job.id,epoch);
}
async function pollJob(id,epoch){
  try{const job=await api('/api/job?id='+encodeURIComponent(id));if(!state.job||state.job.id!==id||epoch!==state.epoch)return;
    if(job.status==='queued'||job.status==='running'){
      let info=typeof job.progress==='string'?job.progress:job.progress?.status||job.progress?.stage||'';status(msg('jobProgress',{status:msg(job.status==='queued'?'queued':'processing'),detail:info?' · '+info:''}));setTimeout(()=>pollJob(id,epoch),1000);return;
    }
    const operation=state.job.operation;state.job=null;markStatus();
    if(job.status==='failed')throw (job.error?new Error(job.error):uiError(msg('jobFailed')));
    if(operation==='native-preview'){
      const data=await api('/api/project');if(epoch!==state.epoch)return;state.preview=data.preview||(job.result?.url?job.result:null);state.manifest=data.manifest||state.preview?.manifest||state.manifest;await refreshViewport(false);renderAll();status(msg('nativeLoaded'));
    }else{showResults(job.result);status(msg('outputVerified'));toast(msg('outputComplete'));}
  }catch(error){if(state.job?.id===id)state.job=null;markStatus();fail(error);showErrorDetails(error,!native()||!!state.preview);if(native()&&!state.preview)showViewportMessage(msg('nativePreviewFailed'),localizedError(error),msg('regeneratePreview'),()=>startJob('native-preview'));}
}
function showResults(result){
  $('results-panel').hidden=false;$('results-toggle').hidden=false;setText($('results-toggle'),msg('viewResults'));
  const entries=Array.isArray(result)?result:Array.isArray(result?.results)?result.results:Array.isArray(result?.shots)?result.shots:[result];
  let html='';for(const entry of entries.filter(Boolean)){
    if(entry.video_url)html+=`<video controls preload="metadata" src="${esc(entry.video_url)}"></video>`;
    const previews=entry.previews_urls||entry.preview_urls||[];for(const url of previews)html+=`<a href="${esc(url)}" target="_blank" rel="noopener"><img src="${esc(url)}" alt="${esc(msg('renderPreviewAlt'))}" data-i18n-alt="authoring.renderPreviewAlt"></a>`;
    if(!previews.length&&entry.contact_sheet_url)html+=`<a href="${esc(entry.contact_sheet_url)}" target="_blank" rel="noopener"><img src="${esc(entry.contact_sheet_url)}" alt="${esc(msg('contactSheetAlt'))}" data-i18n-alt="authoring.contactSheetAlt"></a>`;
    html+='<div class="result-links">'+(entry.video_url?`<a href="${esc(entry.video_url)}" download><span data-i18n="authoring.downloadMp4">${esc(msg('downloadMp4'))}</span></a>`:'')+(entry.check_url?`<a href="${esc(entry.check_url)}" target="_blank" rel="noopener"><span data-i18n="authoring.viewCheckReport">${esc(msg('viewCheckReport'))}</span></a>`:'')+(entry.contact_sheet_url?`<a href="${esc(entry.contact_sheet_url)}" target="_blank" rel="noopener"><span data-i18n="authoring.contactSheet">${esc(msg('contactSheet'))}</span></a>`:'')+'</div>';
  }
  $('results-content').innerHTML=html||`<p class="help-text"><span data-i18n="authoring.noResultImages">${esc(msg('noResultImages'))}</span></p>`;setText($('result-meta'),msg('localOutputComplete'));
}
function showDialog(title,content,submit,handler){
  dialogContent=content;dialogError=null;
  setText($('dialog-title'),title);$('dialog-content').innerHTML=content();$('dialog-error').hidden=true;setText($('dialog-submit'),submit||msg('done'));$('dialog-submit').hidden=!submit;$('dialog-submit').disabled=false;dialogHandler=handler;$('workspace-dialog').showModal();
}
function showNew(){if(!discard())return;showDialog(msg('newAnimationProject'),()=>`<div class="template-options">${[['box',msg('boxTemplate'),'cube'],['lamp',msg('lampTemplate'),'light'],['blank',msg('blankTemplate'),'plus']].map(([id,title,symbol],i)=>`<label class="template-option">${icon(symbol)}<span>${title}</span><input type="radio" name="template" value="${id}" ${i===0?'checked':''}></label>`).join('')}</div><label class="field block"><span class="muted">${esc(msg('projectName'))}</span><input id="new-name" placeholder="my-blender2easy-project" pattern="[A-Za-z0-9_-]+" value="my-animation" required></label><p class="dialog-help">${esc(msg('newProjectHelp'))}</p>`,msg('createProject'),async()=>{state.loading=true;markStatus();try{const data=await api('/api/new',{template:document.querySelector('input[name=template]:checked').value,name:$('new-name').value.trim()});$('workspace-dialog').close();state.loading=false;await acceptProject(data);}finally{state.loading=false;markStatus();}});}
function showOpen(importBlend=false){
  if(!discard())return;showDialog(importBlend?msg('importBlend'):msg('openLocalProject'),()=>`<label class="field block"><span class="muted">${importBlend?msg('blendPath'):msg('projectPath')}</span><input id="open-path" class="dialog-path" placeholder="C:\\Projects\\${importBlend?'model.blend':'project.json'}" required></label>${importBlend?`<label class="field block"><span class="muted">${esc(msg('newProjectName'))}</span><input id="import-name" value="native-scene" pattern="[A-Za-z0-9_-]+" required></label>`:''}<p class="dialog-help">${importBlend?msg('importHelp'):msg('openHelp')}</p>${!importBlend&&state.projects.length?`<div class="property-section"><h3>${esc(msg('recentProjects'))}</h3>`+state.projects.slice(0,8).map((p,i)=>`<button type="button" class="recent-project quiet" data-recent="${i}">${icon('folder')}${esc(p.title||p.id)}</button>`).join('')+'</div>':''}`,importBlend?msg('importScene'):msg('openProject'),async()=>{
    const path=$('open-path').value.trim();if(!path)throw uiError(msg('enterPath'));if(!importBlend&&path.toLowerCase().endsWith('.blend'))throw uiError(msg('useImportBlend'));state.loading=true;markStatus();status(importBlend?msg('readingBlend'):msg('openingProject'));try{const data=await api(importBlend?'/api/import-blend':'/api/open',{path,...(importBlend?{name:$('import-name').value.trim()}:{})});$('workspace-dialog').close();state.loading=false;await acceptProject(data);}finally{state.loading=false;markStatus();}
  });
}
function showAdd(){if(native())return;showDialog(msg('addSceneObject'),()=>`<div class="add-grid">${['cube','cylinder','sphere','empty'].map(type=>`<button type="button" data-add="${type}">${icon('cube')}${typeNames[type]}</button>`).join('')}</div><p class="dialog-help">${esc(msg('addObjectHelp'))}</p>`,null,null);}
function showJson(){showDialog(msg('advancedJson'),()=>`<p class="dialog-help" style="margin:0 0 12px">${esc(msg('advancedJsonHelp'))}</p><textarea aria-label="${esc(msg('advancedJson'))}" id="json-input" class="json-editor" spellcheck="false">${esc(JSON.stringify(state.project,null,2))}</textarea>`,msg('validateApply'),async()=>{let project;try{project=JSON.parse($('json-input').value);}catch{throw uiError(msg('invalidJson'));}if(Boolean(project.source)!==native())throw uiError(msg('switchProjectType'));await api('/api/plan',{project,shot:project.shots?.[0]?.id,path:state.path});mutate(()=>{state.project=project;state.shot=0;},msg('jsonApplied'),{replan:true});$('workspace-dialog').close();});}
function setup(){
  $('dialog-content').addEventListener('click',e=>{const recent=e.target.closest('[data-recent]'),add=e.target.closest('[data-add]');if(recent)$('open-path').value=state.projects[Number(recent.dataset.recent)].path;if(add)addObject(add.dataset.add);});
  viewport=new Viewport($('viewport'),{onSelect:(id)=>select(id),onTransform:(id,value)=>updateTransform(id,value)});
  $('inspector').addEventListener('input',e=>{if(e.target instanceof HTMLInputElement||e.target instanceof HTMLTextAreaElement)e.target.dataset.editing='true';});
  $('inspector').addEventListener('change',e=>{if(e.target instanceof HTMLElement)delete e.target.dataset.editing;},true);
  $('inspector').addEventListener('focusin',()=>{if(state.playing&&!translating)stop();});
  bind('new-btn',showNew);bind('open-btn',()=>showOpen());bind('import-btn',()=>showOpen(true));bind('add-btn',showAdd);bind('save-btn',async()=>{await saveProject();toast(msg('projectSaved'));});bind('undo-btn',()=>undo());bind('redo-btn',()=>undo(true));bind('preview-btn',()=>startJob('preview'));bind('render-btn',()=>startJob('run'));
  bind('object-search',renderHierarchy,'input');for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>{state.tab=b.dataset.tab;renderInspector();};
  for(const b of document.querySelectorAll('[data-mode]'))b.onclick=()=>{for(const e of document.querySelectorAll('[data-mode]'))e.classList.toggle('active',e===b);viewport.setMode(b.dataset.mode);};
  bind('fit-btn',()=>{state.viewCamera='';viewport.setCamera(null);viewport.frameAll();updateProjectLabels();});bind('grid-toggle',e=>viewport.setGrid(e.target.checked),'change');bind('view-camera',e=>{state.viewCamera=e.target.value;viewport.setCamera(state.viewCamera||null);},'change');
  bind('shot-select',async e=>{stop();state.shot=Number(e.target.value);state.index=0;state.plan=null;renderInspector();await loadPlan();updateProjectLabels();},'change');
  bind('shot-add',()=>mutate(()=>{const original=clone(shot());original.id=uniqueId('shot',state.project.shots);original.title=String(msg('newShotTitle',{count:displayNumber(state.project.shots.length+1)}));state.project.shots.push(original);state.shot=state.project.shots.length-1;state.index=0;},msg('shotAdded'),{rebuild:false,replan:true}));
  bind('autokey',e=>{state.autoKey=e.target.checked;renderInspector();},'change');
  bind('key-add',()=>{const item=selectedObject();if(!item||native())return;const values=currentTransform(item);mutate(()=>{for(const p of ['location','rotation_deg','scale'])addKey(item.id,p,values[p]||(p==='scale'?[1,1,1]:[0,0,0]));},msg('poseRecorded',{frame:displayNumber(state.frame)}));});
  bind('timeline',e=>{stop();setIndex(Number(e.target.value));},'input');bind('first-frame',()=>{stop();setIndex(0);});bind('last-frame',()=>{stop();setIndex(state.plan?.sourceFrames.length-1||0);});bind('play-btn',()=>{if(!state.plan?.sourceFrames?.length)return;state.playing=!state.playing;$('play-btn').innerHTML=icon(state.playing?'pause':'play');$('play-btn').removeAttribute('data-i18n-aria-label');$('play-btn').setAttribute('aria-label',state.playing?msg('pause'):msg('play'));animationTime=performance.now();if(!state.playing)renderInspector();});
  bind('results-close',()=>$('results-panel').hidden=true);bind('results-toggle',()=>$('results-panel').hidden=!$('results-panel').hidden);
  $('workspace-form').addEventListener('submit',async e=>{if(e.submitter?.value==='cancel')return;e.preventDefault();if(!dialogHandler)return;$('dialog-submit').disabled=true;$('dialog-error').hidden=true;try{await dialogHandler();}catch(error){const detailed=hasErrorDetails(error);dialogError=error;setText($('dialog-error'),{toString:()=>shortMessage(errorText(dialogError))+(detailed?msg('dialogErrorHelp'):'')});$('dialog-error').hidden=false;if(detailed)showErrorDetails(error);}finally{$('dialog-submit').disabled=false;}});
  document.addEventListener('keydown',handleWorkspaceShortcut);
  window.addEventListener('beforeunload',e=>{if(dirty()||state.job){e.preventDefault();e.returnValue='';}});requestAnimationFrame(animate);
}
function handleWorkspaceShortcut(e){
  if(e.defaultPrevented)return;
  const active=document.activeElement;
  const editing=['INPUT','TEXTAREA','SELECT'].includes(active?.tagName)||active?.isContentEditable||$('workspace-dialog').open;
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();if(!state.saving&&!state.loading)guard(saveProject)();return;}
  if(editing)return;
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();undo(e.shiftKey);return;}
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();undo(true);return;}
  if(e.code==='Space'){
    // A focused control owns Space; the workspace shortcut applies to the canvas.
    if(active?.closest?.('button,summary,a,[role="button"],[role="tab"],[role="menuitem"]'))return;
    e.preventDefault();$('play-btn').click();return;
  }
  const mode={w:'translate',e:'rotate',r:'scale'}[e.key.toLowerCase()];
  if(mode&&!e.ctrlKey&&!e.metaKey)document.querySelector(`[data-mode="${mode}"]`).click();
  if(e.key.toLowerCase()==='f'&&!e.ctrlKey&&!e.metaKey)$('fit-btn').click();
}
async function init(){
  try{setup();const session=await api('/api/session');state.token=session.token;state.projects=session.projects||[];if(session.current)await acceptProject(session.current);else{const data=await api('/api/project');await acceptProject(data);}}
  catch(error){fail(error);setText($('connection-status'),msg('connectionFailed'));showViewportMessage(msg('workspaceNotReady'),localizedError(error),msg('reconnect'),()=>location.reload());}
}
// Translation is a display operation: no project mutation, save, reload, plan request or viewport reset.
function preserveControls(root, render) {
  const controls=[...root.querySelectorAll('input,textarea,select')];
  const drafts=controls.map(node=>({value:node.value,checked:node.checked,editing:node.dataset.editing,scrollTop:node.scrollTop,scrollLeft:node.scrollLeft,start:node.selectionStart,end:node.selectionEnd,direction:node.selectionDirection}));
  const focused=controls.indexOf(document.activeElement),scrollTop=root.scrollTop,scrollLeft=root.scrollLeft;
  render();
  [...root.querySelectorAll('input,textarea,select')].forEach((node,index)=>{const draft=drafts[index];if(!draft)return;node.value=draft.value;if('checked' in node)node.checked=draft.checked;if(draft.editing)node.dataset.editing=draft.editing;else delete node.dataset.editing;try{if(draft.start!==null)node.setSelectionRange(draft.start,draft.end,draft.direction);}catch{}node.scrollTop=draft.scrollTop;node.scrollLeft=draft.scrollLeft;if(index===focused)node.focus({preventScroll:true});});
  root.scrollTop=scrollTop;root.scrollLeft=scrollLeft;
}
function refreshLanguage(){
  translating=true;
  try {
  translatePage();
  if(state.project){const treeScroll=$('hierarchy').scrollTop;updateProjectLabels();renderHierarchy();$('hierarchy').scrollTop=treeScroll;preserveControls($('inspector'),renderInspector);renderTimeline();markStatus();}
  if($('workspace-dialog').open&&dialogContent)preserveControls($('dialog-content'),()=>{$('dialog-content').innerHTML=dialogContent();});
  if(viewportMessage&&!$('viewport-message').hidden)showViewportMessage(...viewportMessage);
  $('play-btn').removeAttribute('data-i18n-aria-label');$('play-btn').setAttribute('aria-label',String(msg(state.playing?'pause':'play')));
  for(const [element,value] of textBindings){if(element.isConnected)element.textContent=String(value??'');else textBindings.delete(element);}
  } finally {translating=false;}
}
initPreferences();
translatePage();
onLocaleChange(refreshLanguage);
init();
