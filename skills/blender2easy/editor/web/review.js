import {Viewport} from '/viewport.js';
import {registerMessages, t, formatNumber, initPreferences, translatePage, onLocaleChange, localizeError} from '/i18n.js';
import {messages} from '/locales/review.js';

registerMessages(messages);
initPreferences();
translatePage();

const $ = id => document.getElementById(id);
const clone = value => structuredClone(value);
const stageInfo = {
  model: {label:'review.stage.model.label', view:'review.stage.model.label', heading:'review.stage.model.heading', scope:'review.stage.model.scope', help:'review.stage.model.help', placeholder:'review.stage.model.placeholder'},
  motion: {label:'review.stage.motion.label', view:'review.stage.motion.label', heading:'review.stage.motion.label', scope:'review.stage.motion.scope', help:'review.stage.motion.help', placeholder:'review.stage.motion.placeholder'},
  camera: {label:'review.stage.camera.label', view:'review.stage.camera.label', heading:'review.stage.camera.heading', scope:'review.stage.camera.scope', help:'review.stage.camera.help', placeholder:'review.stage.camera.placeholder'},
  delivery: {label:'review.stage.delivery.label', view:'review.stage.delivery.label', heading:'review.stage.delivery.heading', scope:'review.stage.delivery.scope', help:'review.stage.delivery.help', placeholder:'review.stage.delivery.placeholder'},
  waiting: {label:'review.preview', view:'review.preview', heading:'', scope:'', help:'review.stage.waiting.help', placeholder:''},
};
const state = {token:null,current:null,review:null,base:null,candidate:null,values:{},defaults:{},frame:1,index:0,frames:[1],fullFrames:[1],fps:24,annotation:null,compare:false,freeView:false,playing:false,playStart:0,playIndex:0,viewSeq:0,previewSeq:0,previewValid:false,previewBusy:false,submitBusy:false,nativeBusy:false,stale:false,note:'',pollBusy:false,requestId:null,referenceId:null,referenceOpen:false,checkpointId:null,reviewCameraId:null};
Object.assign(state,{findingId:null,inspectionTool:null,isolate:false,xray:false,snapEnabled:true});
const linkRequest = new URLSearchParams(location.search).get('request');
let viewport, debounceTimer, toastTimer, pollTimer, receiptSignature, referenceObserver;
let statusMessage=null, toastMessage=null, lastError=null, loadingKey='review.loadingView', connectionKey='review.connecting';
let inspectionMissReason=null;
let inspectionHoverCandidate=null;
const numberText=(value,options={})=>formatNumber(Number(value),{maximumFractionDigits:10,...options});
const secondsText=value=>t('review.seconds',{value:numberText(value,{minimumFractionDigits:2,maximumFractionDigits:2})});
const frameText=value=>numberText(value,{maximumFractionDigits:2});
function uiError(key,params={}) {const error=new Error(t(key,params));error.i18nKey=key;error.i18nParams=params;return error;}
function errorText(error) {return error?.i18nKey?t(error.i18nKey,error.i18nParams):localizeError(error?.serverError||error);}
function loadingText(key) {loadingKey=key;$('loading-text').textContent=t(key);}

function el(tag, className, text) {
  const node=document.createElement(tag);
  if(className) node.className=className;
  if(text!==undefined) node.textContent=text;
  return node;
}
function messageText(message) {return t(message.key,Object.fromEntries(Object.entries(message.params).map(([key,value])=>[key,typeof value==='number'?numberText(value):value])));}
function status(key, error=false, params={}) {statusMessage={key,error,params};$('preview-status').textContent=messageText(statusMessage);$('preview-status').classList.toggle('error-text',error);if(error)setInspector(true);}
function showError(error) {lastError=error;$('error-banner').textContent=errorText(error);$('error-banner').hidden=false;setInspector(true);}
function clearError() {lastError=null;$('error-banner').hidden=true;}
function toast(key,params={}) {toastMessage={key,params};clearTimeout(toastTimer);$('toast').textContent=t(key,params);$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,3000);}
function request() { return state.review?.request; }
function stage() { return request()?.stage||'waiting'; }
function editable() { return !!request() && state.review.status==='pending' && !state.stale && !state.submitBusy; }
function sourceRange() { return request()?.focus?.source_range || state.current?.project?.shots?.[0]?.source_range || [1,48]; }
function references() { return request()?.evidence?.references||[]; }
function checkpoints() { return request()?.evidence?.checkpoints||[]; }
function findings() { return request()?.evidence?.findings||[]; }
function findingEvidenceState() {
  if(!findings().length) return 'none';
  return !state.compare && Object.keys(state.defaults).some(key=>JSON.stringify(state.values[key])!==JSON.stringify(state.defaults[key])) ? 'candidate-unchecked' : 'original';
}
function updateFindingEvidence() {
  const label=$('finding-evidence-status');
  if(!label) return;
  const evidence=findingEvidenceState();
  label.dataset.state=evidence;
  label.textContent=evidence==='candidate-unchecked'?t('review.evidence.changed'):evidence==='original'?t('review.evidence.original'):'';
  label.title=evidence==='candidate-unchecked'?t('review.evidence.changedHelp'):t('review.evidence.originalHelp');
}
function activeFinding() { return findings().find(item=>item.id===state.findingId&&item.source_frame===state.frame)||null; }
function inspectionIds() { return request()?.inspection?.object_ids||[]; }
function inspectionFocus() { return (activeFinding()?.object_ids||activeCheckpoint()?.object_ids||(state.annotation?.object_id?[state.annotation.object_id]:request()?.focus?.object_ids)||inspectionIds()).filter(id=>inspectionIds().includes(id)); }
function activeCheckpoint() { return checkpoints().find(item=>item.id===state.checkpointId&&item.source_frame===state.frame&&item.reference_id===state.referenceId)||null; }
function reviewCamera() { return state.reviewCameraId||request()?.focus?.camera_id||state.current?.project?.shots?.[0]?.camera||null; }
function referenceTitle(id) { return references().find(item=>item.id===id)?.title||id; }
function annotationText(annotation) {
  if(!annotation) return '';
  const checkpoint=checkpoints().find(item=>item.id===annotation.checkpoint_id);
  const finding=findings().find(item=>item.id===annotation.finding_id);
  const parts=[finding?.title||checkpoint?.title||checkpoint?.id,annotation.object_id?objectLabel(annotation.object_id):null,annotation.reference_id?referenceTitle(annotation.reference_id):null];
  if(annotation.points?.length) parts.push(t(annotation.points.length===1?'review.annotation.point':'review.annotation.points',{count:numberText(annotation.points.length),variant:t(annotation.preview_variant==='original'?'review.annotation.originalSurface':'review.annotation.currentPreview')}));
  if(Number.isFinite(annotation.measurement?.display_distance)&&['m','cm','mm'].includes(annotation.measurement.display_units)) {
    parts.push(t('review.annotation.modelDimension',{value:numberText(annotation.measurement.display_distance,{maximumSignificantDigits:5}),unit:annotation.measurement.display_units}));
  } else if(Number.isFinite(annotation.measurement?.distance)) {
    parts.push(t(annotation.measurement.units==='m'?'review.annotation.modelDimension':'review.annotation.previewDistance',{value:numberText(annotation.measurement.distance,{maximumSignificantDigits:5}),unit:'m'}));
  }
  if(annotation.reference_uv) parts.push(t('review.annotation.mark',{x:numberText(Math.round(annotation.reference_uv[0]*100)),y:numberText(Math.round(annotation.reference_uv[1]*100))}));
  if(Number.isFinite(annotation.source_frame)) parts.push(t('review.annotation.frame',{frame:frameText(annotation.source_frame)}));
  return parts.filter(Boolean).join(' · ');
}
function locationAnnotation() {
  const annotation={source_frame:state.frame};
  const checkpoint=activeCheckpoint();
  if(checkpoint) annotation.checkpoint_id=checkpoint.id;
  if(activeFinding()) annotation.finding_id=activeFinding().id;
  if(state.referenceId) annotation.reference_id=state.referenceId;
  return annotation;
}
function keyboardTabs(event,box) {
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
  const tabs=[...box.querySelectorAll('[role=tab]:not(:disabled)')],current=tabs.indexOf(event.target);
  if(current<0||!tabs.length) return;
  event.preventDefault();
  const index=event.key==='Home'?0:event.key==='End'?tabs.length-1:(current+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  tabs[index].focus();tabs[index].click();
}
function renderEvidence() {
  const hasReferences=references().length>0,box=$('checkpoints');box.replaceChildren();box.hidden=!checkpoints().length;
  for(const checkpoint of checkpoints()) {
    const button=el('button','segment',checkpoint.title||checkpoint.id);button.type='button';button.id='checkpoint-'+checkpoint.id;
    button.dataset.checkpointId=checkpoint.id;button.setAttribute('role','tab');button.setAttribute('aria-controls','model-pane');
    button.title=t('review.checkpointTitle',{title:checkpoint.title||checkpoint.id,frame:frameText(checkpoint.source_frame)});
    button.addEventListener('click',()=>selectCheckpoint(checkpoint));box.append(button);
  }
  $('reference-toggle').hidden=!hasReferences;
  const tabs=$('reference-tabs');tabs.replaceChildren();
  for(const reference of references()) {
    const button=el('button','reference-tab',reference.title||reference.id);button.type='button';button.dataset.referenceId=reference.id;
    button.setAttribute('role','tab');button.setAttribute('aria-controls','reference-surface');button.title=reference.title||reference.id;
    button.addEventListener('click',()=>selectReference(reference.id));tabs.append(button);
  }
  renderReference();updateCheckpointTabs();
  renderFindings();renderInspection();
}
function renderFindings() {
  const box=$('findings');box.replaceChildren();box.hidden=!findings().length;
  $('workspace').dataset.findings=String(findings().length>0);
  const evidenceLabel=el('span','finding-evidence-status');evidenceLabel.id='finding-evidence-status';
  evidenceLabel.setAttribute('role','status');evidenceLabel.setAttribute('aria-live','polite');box.append(evidenceLabel);
  for(const finding of findings()) {
    const button=el('button','finding-chip',finding.title||finding.id);button.type='button';
    button.dataset.findingId=finding.id;button.dataset.severity=finding.severity||'info';
    button.setAttribute('role','tab');button.setAttribute('aria-controls','model-pane');
    updateFindingLabel(button,finding);
    button.addEventListener('click',()=>selectFinding(finding));box.append(button);
  }
  updateFindingTabs();
  updateFindingEvidence();
}
function updateFindingLabel(button,finding) {
  const title=finding.title||finding.id;
  button.setAttribute('aria-label',t('review.findingLabel',{severity:t('review.severity.'+(finding.severity||'info')),title}));
  button.title=t('review.findingTitle',{title,frame:frameText(finding.source_frame)});
}
function updateFindingTabs() {
  const active=activeFinding();
  for(const [index,button] of [...$('findings').querySelectorAll('[data-finding-id]')].entries()) {
    const selected=button.dataset.findingId===active?.id;
    button.setAttribute('aria-selected',String(selected));button.tabIndex=selected||(!active&&index===0)?0:-1;
  }
}
function selectFinding(finding) {
  stopPlayback();state.frame=finding.source_frame;state.index=closestIndex(state.frames,state.frame);
  state.findingId=finding.id;state.checkpointId=null;state.reviewCameraId=finding.camera_id;
  state.referenceId=finding.reference_id||null;state.referenceOpen=!!finding.reference_id;state.freeView=false;
  if(editable()) state.annotation={...locationAnnotation(),...(finding.object_ids?.[0]?{object_id:finding.object_ids[0]}:{})};
  else clearSurfacePoints();
  viewport?.setFrame(state.frame);viewport?.setCamera(reviewCamera());viewport?.select(finding.object_ids?.[0]||null);
  syncInspection();renderReference();renderCompare();updatePosition();
  if(stage()==='delivery'&&!$('review-video').hidden) $('review-video').currentTime=closestIndex(state.fullFrames,state.frame)/state.fps;
}
function clearSurfacePoints() {
  inspectionMissReason=null;
  if(state.annotation?.points) {state.annotation={...state.annotation};delete state.annotation.points;delete state.annotation.measurement;delete state.annotation.preview_variant;delete state.annotation.sampled_values;}
  viewport?.setInspectionPoints([]);
}
function inspectionDistance(annotation) {
  // A saved receipt keeps its server-provided measurement. Live picking uses
  // the viewport's shared calculation, without changing submission coordinates.
  const measurement=annotation?.measurement||viewport?.inspectionMeasurement?.();
  if(!measurement) return '';
  const distance=measurement.display_distance??measurement.distance;
  if(!Number.isFinite(distance)) return '';
  const units=measurement.display_units??measurement.units;
  return t('review.inspection.distance',{value:numberText(distance,{maximumSignificantDigits:5,useGrouping:false}),unit:['m','cm','mm'].includes(units)?units:t('review.inspection.previewUnits')});
}
function renderInspectionHint(step,title='',detail='') {
  const hint=$('inspection-hint');
  const missed=!!inspectionMissReason&&editable()&&['ready','first','complete','point-ready','point-recorded'].includes(step);
  if(missed) {
    detail=step==='first'?t('review.inspection.missSelectB'):step==='point-recorded'?t('review.inspection.missMovePoint'):step==='complete'?t('review.inspection.missRestart',{measurement:title}):t('review.inspection.missSelectA');
    if(request()?.inspection?.tools?.includes('isolate')&&!state.isolate) detail+=' '+t('review.inspection.isolateSuggestion');
    title=t('review.inspection.miss');
  }
  const signature=JSON.stringify([title,detail]);
  hint.dataset.step=step;
  hint.dataset.feedback=missed?'miss':'normal';
  hint.setAttribute('aria-live','polite');hint.setAttribute('aria-atomic','true');
  // Repeated position/lock refreshes must not repeatedly announce the same step.
  if(hint.dataset.message===signature) return;
  hint.dataset.message=signature;hint.replaceChildren();
  if(title) hint.append(el('span','inspection-hint-title',title));
  if(detail) hint.append(el('span','inspection-hint-detail',detail));
}
function handleInspectionMiss(reason) {
  if(!editable()||state.nativeBusy||state.previewBusy||!state.previewValid||!['point','measure'].includes(state.inspectionTool)) return;
  if(!['out-of-scope','outside-view','no-surface','empty'].includes(reason)) return;
  inspectionMissReason=reason;inspectionHoverCandidate=null;renderInspection();
}
function handleInspectionHover(info) {
  inspectionHoverCandidate=info&&['vertex','edge','surface','unavailable'].includes(info.kind)?{kind:info.kind,reason:info.reason}:null;
  renderInspectionCandidate();
}
function renderInspectionCandidate() {
  const label=$('inspection-candidate');
  if(!label) return;
  const active=editable()&&!state.nativeBusy&&!state.previewBusy&&state.previewValid&&['point','measure'].includes(state.inspectionTool);
  let candidate=active?inspectionHoverCandidate:null;
  if(candidate&&!state.snapEnabled) candidate={kind:'surface'};
  label.hidden=!candidate;
  label.dataset.kind=candidate?.kind||'none';
  const text=candidate?t('review.inspection.candidate.'+candidate.kind):'';
  if(label.textContent!==text) label.textContent=text;
  label.title=candidate?.kind==='unavailable'?t('review.inspection.snapUnavailable.'+(['deformed','instanced','dense'].includes(candidate.reason)?candidate.reason:'default')):'';
}
function toggleInspectionSnap() {
  if(!editable()||state.nativeBusy||state.previewBusy||!state.previewValid||!['point','measure'].includes(state.inspectionTool)) return;
  state.snapEnabled=!state.snapEnabled;
  viewport?.setInspectionSnap?.(state.snapEnabled);
  renderInspection();
}
function renderInspection() {
  const tools=request()?.inspection?.tools||[],visible=stage()!=='delivery'&&tools.length>0;
  $('inspection-tools').hidden=!visible;
  for(const button of $('inspection-tools').querySelectorAll('[data-inspection-tool]')) {
    const tool=button.dataset.inspectionTool;button.hidden=!tools.includes(tool);
    button.disabled=state.nativeBusy||(['point','measure'].includes(tool)&&(!editable()||state.previewBusy||!state.previewValid));
    button.setAttribute('aria-pressed',String(tool==='isolate'?state.isolate:tool==='xray'?state.xray:state.inspectionTool===tool));
  }
  const annotation=state.annotation?.source_frame===state.frame?state.annotation:null;
  const count=annotation?.points?.length||0,tool=state.inspectionTool;
  const ready=editable()&&!state.nativeBusy&&!state.previewBusy&&state.previewValid;
  const snap=$('inspection-snap');
  if(snap) {
    snap.hidden=!visible||!['point','measure'].includes(tool)||!editable();
    snap.disabled=!ready;snap.textContent=t('review.inspection.snap');
    snap.setAttribute('aria-pressed',String(state.snapEnabled));
    snap.setAttribute('aria-label',t('review.inspection.snapLabel'));
    snap.title=t(state.snapEnabled?'review.inspection.snapDisable':'review.inspection.snapEnable');
  }
  renderInspectionCandidate();
  const restart=$('inspection-restart');
  if(restart) {
    restart.hidden=!visible||tool!=='measure'||count!==2||!editable();
    restart.disabled=!ready;restart.textContent=t('review.inspection.restart');
    restart.setAttribute('aria-label',t('review.inspection.restart'));
  }
  if(!visible||!['measure','point'].includes(tool)) {renderInspectionHint('idle');return;}
  if(editable()&&!ready) {renderInspectionHint('waiting',t('review.inspection.notReady'),t('review.inspection.notReadyHelp'));return;}
  if(tool==='measure'&&count===2) {
    const distance=inspectionDistance(annotation);
    renderInspectionHint('complete',distance?t('review.inspection.complete',{distance}):t('review.inspection.bothRecorded'),ready?t('review.inspection.completeHelp'):'');
  } else if(count===1) {
    renderInspectionHint(tool==='measure'?'first':'point-recorded',t('review.inspection.firstRecorded'),ready?t(tool==='measure'?'review.inspection.secondPointHelp':'review.inspection.pointRecordedHelp'):'');
  } else if(ready) {
    renderInspectionHint(tool==='measure'?'ready':'point-ready',t(tool==='measure'?'review.inspection.firstPoint':'review.inspection.placePoint'),t('review.inspection.startHelp'));
  } else renderInspectionHint('idle');
}
function restartMeasurement() {
  if(!editable()||state.nativeBusy||state.previewBusy||!state.previewValid||state.inspectionTool!=='measure'||!request()?.inspection?.tools?.includes('measure')) return;
  stopPlayback();clearSurfacePoints();syncInspection();updatePosition();
  viewport?.renderer?.domElement?.focus?.({preventScroll:true});
}
function syncInspection() {
  viewport?.configureInspection(request()?.inspection||null);
  viewport?.setInspectionSnap?.(state.snapEnabled);
  viewport?.setInspectionMode(editable()?state.inspectionTool:null);
  viewport?.setInspectionPoints(state.annotation?.source_frame===state.frame?state.annotation.points||[]:[]);
  viewport?.setIsolation(state.isolate?inspectionFocus():null);viewport?.setXray(state.xray);
  renderInspection();
}
function toggleInspection(tool) {
  if(!request()?.inspection?.tools?.includes(tool)) return;
  inspectionMissReason=null;
  if(tool==='isolate') state.isolate=!state.isolate;
  else if(tool==='xray') state.xray=!state.xray;
  else {
    if(!editable()) return;
    stopPlayback();state.inspectionTool=state.inspectionTool===tool?null:tool;clearSurfacePoints();
  }
  syncInspection();updatePosition();
}
function selectSurface(point) {
  if(!editable()||state.previewBusy||!state.previewValid||!inspectionIds().includes(point.object_id)||!['point','measure'].includes(state.inspectionTool)) return;
  inspectionMissReason=null;
  stopPlayback();
  const previous=state.annotation?.source_frame===state.frame?state.annotation:{};
  // Snapping metadata is viewing state. Persist only the supported point shape.
  const sample={object_id:point.object_id,local:[...point.local],world:[...point.world]};
  const points=state.inspectionTool==='measure'&&previous.points?.length===1?[...previous.points,sample]:[sample];
  state.annotation={...previous,...locationAnnotation(),object_id:point.object_id,points,preview_variant:state.compare?'original':'candidate'};
  delete state.annotation.measurement;
  viewport?.setInspectionPoints(points);updatePosition();
}
function updateCheckpointTabs() {
  const active=activeCheckpoint();
  for(const [index,button] of [...$('checkpoints').querySelectorAll('[data-checkpoint-id]')].entries()) {
    const selected=button.dataset.checkpointId===active?.id;
    button.setAttribute('aria-selected',String(selected));button.tabIndex=selected||(!active&&index===0)?0:-1;
  }
}
function renderReference() {
  const reference=references().find(item=>item.id===state.referenceId),visible=!!reference&&state.referenceOpen;
  $('preview-content').dataset.reference=visible?'open':'closed';$('reference-pane').hidden=!visible;
  const button=$('reference-toggle');button.setAttribute('aria-expanded',String(visible));button.setAttribute('aria-label',visible?t('review.hideReferenceImage'):t('review.showReferenceImage'));button.title=visible?t('review.hideReference'):t('review.showReference');
  for(const tab of $('reference-tabs').querySelectorAll('[data-reference-id]')) {
    const selected=tab.dataset.referenceId===state.referenceId;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;
  }
  const image=$('reference-image'),url=reference?state.review?.reference_urls?.[reference.id]:null;
  image.alt=reference?.title||t('review.referenceImage');
  if(url&&image.getAttribute('src')!==url) {image.hidden=false;$('reference-error').hidden=true;image.setAttribute('src',url);}
  else if(!url) {image.removeAttribute('src');image.hidden=true;$('reference-error').hidden=!reference;}
  updateReferenceMark();
}
function selectReference(id) {
  if(!references().some(item=>item.id===id)) return;
  state.referenceId=id;
  if(activeFinding()?.reference_id&&activeFinding().reference_id!==id) {state.findingId=null;if(state.annotation) {state.annotation={...state.annotation};delete state.annotation.finding_id;}}
  if(state.annotation?.reference_id!==id&&editable()) {
    if(state.annotation?.object_id) state.annotation={source_frame:state.annotation.source_frame,object_id:state.annotation.object_id};
    else state.annotation=null;
  }
  if(!activeCheckpoint()) state.checkpointId=null;
  syncInspection();renderReference();updatePosition();
}
function selectCheckpoint(checkpoint) {
  state.findingId=null;clearSurfacePoints();
  stopPlayback();state.frame=checkpoint.source_frame;state.index=closestIndex(state.frames,state.frame);
  state.checkpointId=checkpoint.id;state.reviewCameraId=checkpoint.camera_id;state.referenceId=checkpoint.reference_id;state.freeView=false;
  // A checkpoint is a viewing preset. It never grants parameter or transform access.
  if(editable()) state.annotation=locationAnnotation();
  viewport?.setFrame(state.frame);viewport?.setCamera(reviewCamera());viewport?.select(checkpoint.object_ids?.[0]||null);
  syncInspection();renderReference();renderCompare();updatePosition();
  if(stage()==='delivery'&&!$('review-video').hidden) $('review-video').currentTime=closestIndex(state.fullFrames,state.frame)/state.fps;
}
function imageContentRect() {
  const image=$('reference-image'),surface=$('reference-surface'),rect=surface.getBoundingClientRect();
  if(image.hidden||!image.complete||!image.naturalWidth||!rect.width||!rect.height) return null;
  const scale=Math.min(rect.width/image.naturalWidth,rect.height/image.naturalHeight),width=image.naturalWidth*scale,height=image.naturalHeight*scale;
  return {left:(rect.width-width)/2,top:(rect.height-height)/2,width,height,surface:rect};
}
function updateReferenceMark() {
  const annotation=state.annotation,rect=imageContentRect(),mark=$('reference-mark');
  const visible=!!rect&&annotation?.source_frame===state.frame&&annotation?.reference_id===state.referenceId&&!!annotation?.reference_uv;
  mark.hidden=!visible;
  if(visible) {mark.style.left=`${rect.left+annotation.reference_uv[0]*rect.width}px`;mark.style.top=`${rect.top+annotation.reference_uv[1]*rect.height}px`;}
}
function markReference(uv) {
  if(!editable()||!state.referenceId||!imageContentRect()) return;
  stopPlayback();
  const previous=state.annotation?.source_frame===state.frame?state.annotation:{};
  state.annotation={...previous,...locationAnnotation(),reference_uv:uv.map(value=>Math.max(0,Math.min(1,value)))};
  if(!activeCheckpoint()) delete state.annotation.checkpoint_id;
  updatePosition();revealFeedback();
}
function referenceClick(event) {
  const rect=imageContentRect();if(!rect) return;
  const x=event.clientX-rect.surface.left-rect.left,y=event.clientY-rect.surface.top-rect.top;
  if(x<0||y<0||x>rect.width||y>rect.height) return;
  markReference([x/rect.width,y/rect.height]);
}
function referenceKey(event) {
  if(!editable()||!['Enter',' ','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Delete','Backspace'].includes(event.key)) return;
  event.preventDefault();
  if(event.key==='Delete'||event.key==='Backspace') {clearAnnotation();return;}
  const uv=state.annotation?.reference_id===state.referenceId&&state.annotation?.reference_uv?[...state.annotation.reference_uv]:[.5,.5],step=event.shiftKey ? .1 : .01;
  if(event.key==='ArrowLeft') uv[0]-=step;if(event.key==='ArrowRight') uv[0]+=step;if(event.key==='ArrowUp') uv[1]-=step;if(event.key==='ArrowDown') uv[1]+=step;
  markReference(uv);
}
function clearAnnotation() {inspectionMissReason=null;state.annotation=null;viewport?.setInspectionPoints([]);viewport?.select(activeFinding()?.object_ids?.[0]||activeCheckpoint()?.object_ids?.[0]||null);updatePosition();}
function setInspector(open) {
  $('workspace').dataset.inspector=open?'open':'closed';
  const button=$('inspector-toggle');
  if(button) {const label=t(request()?.controls?.length?'review.adjustments':'review.feedback'),title=t(open?'review.panel.collapse':'review.panel.expand',{panel:label});button.setAttribute('aria-expanded',String(open));button.setAttribute('aria-label',title);button.title=title;button.querySelector('.toggle-label').textContent=label;}
}
function revealFeedback(focus=false) {
  setInspector(true);
  if($('feedback-details')) $('feedback-details').open=true;
  if(focus) requestAnimationFrame(()=>$('feedback-note').focus());
}
function connectionStatus(key) {
  connectionKey=key;
  const text=t(key);
  $('connection-status').textContent=text;
  $('connection-status').title=text;
  const wrapper=$('connection-status').closest('.connection');
  if(wrapper) wrapper.title=text;
}
function objectLabel(id) {
  const focus=request()?.focus;
  const all=[...(state.current?.project?.scene?.objects||[]),...(state.current?.manifest?.objects||[]),...(state.current?.preview?.manifest?.objects||[])];
  const item=all.find(object=>object.id===id);
  return focus?.object_labels?.[id] || item?.label || item?.name || id;
}
function focusedObject() {
  const ids=request()?.focus?.object_ids||[];
  return ids.find(id=>state.current?.project?.scene?.objects?.find(o=>o.id===id && o.type!=='empty'))||ids[0]||null;
}
function currentSegment() {
  const segments=request()?.segments||[];
  return segments.find(item=>state.frame>=item.source_range?.[0]&&state.frame<=item.source_range?.[1])||segments.find(item=>item.id===request()?.focus?.segment_id);
}
function formatValue(control,value) {
  if(control.kind==='choice') return String(control.options?.find(option=>option.value===value)?.label ?? value);
  return (typeof value==='number'?numberText(value):String(value??'')) + (control.unit||'');
}
async function api(path,body) {
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-Editor-Token':state.token},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
  let result;
  try {result=await response.json();} catch {throw uiError('review.error.unreadableResponse',{status:response.status});}
  if(!response.ok) {
    const detail=result.error||result.message;
    if(detail) {const error=new Error(typeof detail==='string'?detail:JSON.stringify(detail));error.serverError=detail;throw error;}
    throw uiError('review.error.requestFailed',{status:response.status});
  }
  return result;
}
function identity() { return {path:state.current.path,request_id:request().id,revision:request().revision}; }

function renderHeader(refreshNavigation=true) {
  const info=Object.fromEntries(Object.entries(stageInfo[stage()]||stageInfo.waiting).map(([key,value])=>[key,value?t(value):'']));
  $('workspace').dataset.stage=stage();
  $('project-label').textContent=state.current?.project?.title||state.current?.project?.id||t('review.localProject');
  $('stage-label').textContent=info.label;
  $('view-title').textContent=info.view;
  $('request-title').textContent=request()?.title||t('review.currentModel');
  $('request-question').textContent=request()?.question||t('review.waitingReview');
  $('request-context').textContent=request()?.context||'';
  $('request-context').hidden=!request()?.context;
  $('controls-heading').textContent=info.heading;
  $('scope-description').textContent=info.scope;
  $('preview-help').textContent=info.help;
  $('feedback-note').placeholder=info.placeholder;
  $('confirm-btn').textContent=t('review.confirm');
  $('jump-controls').hidden=!request();
  $('stale-banner').hidden=!state.stale;
  if(state.stale) {
    $('stale-banner').replaceChildren(document.createTextNode(t('review.stale.link')));
    if(request()) {const link=el('a','',t('review.stale.openCurrent'));link.href='/preview/'+encodeURIComponent(stage())+'?request='+encodeURIComponent(request().id);link.style.marginLeft='10px';$('stale-banner').append(link);}
    else $('stale-banner').append(document.createTextNode(t('review.stale.askNew')));
  }
  $('orbit-btn').hidden=stage()==='camera'||stage()==='delivery';
  $('focus-btn').hidden=stage()==='delivery';
  $('compare-btn').hidden=!request()||stage()==='delivery';
  $('playback').hidden=stage()!=='motion';
  $('preview-fidelity').hidden=stage()==='delivery';
  document.title=t('review.documentTitle',{title:request()?.title||t('review.animationPreview')});
  if(refreshNavigation) {renderSegments();renderEvidence();}
  setInspector($('workspace').dataset.inspector==='open');
  renderConnection();
}
function renderConnection() {
  const review=state.review;
  connectionStatus(review?.agent_listening?'review.connection.listening':'review.connection.local');
  $('submit-hint').textContent=review?.agent_listening?t('review.connection.listeningHelp'):t('review.connection.savedHelp');
  $('footer-status').textContent=review?.status==='pending'?t('review.connection.scoped'):t('review.connection.localOnly');
}
function renderSegments() {
  const box=$('segments');box.replaceChildren();
  const segments=request()?.segments||[];
  box.hidden=stage()!=='motion'||!segments.length||checkpoints().length>0;
  for(const [index,segment] of segments.entries()) {
    const button=el('button','segment'); button.type='button';
    button.append(el('span','segment-number',numberText(index+1,{minimumIntegerDigits:2,useGrouping:false})),el('span','',segment.title||segment.id));
    const active=segment.id===currentSegment()?.id;
    const range=sourceRange(),intersectionStart=Math.max(range[0],segment.source_range?.[0]??range[0]),intersectionEnd=Math.min(range[1],segment.source_range?.[1]??range[1]);
    button.dataset.segmentId=segment.id;
    button.setAttribute('aria-current',active?'step':'false');
    // Navigation stays within the frozen focus range; it never changes edit scope.
    button.disabled=intersectionStart>intersectionEnd;
    if(!button.disabled) button.addEventListener('click',()=>setFrameNearest(intersectionStart));
    box.append(button);
  }
}
function renderControls() {
  const box=$('controls'); box.replaceChildren();
  const controls=request()?.controls||[];
  $('adjustments').hidden=!controls.length||state.review?.status!=='pending';
  for(const control of controls) {
    const wrapper=el('div','control'); wrapper.dataset.control=control.id;
    const top=el('div','control-top'), label=el('label','',control.label||control.id);
    const inputId='control-'+control.id; label.htmlFor=inputId;top.append(label);wrapper.append(top);
    if(control.kind==='number') {
      const numberWrap=el('div','control-number'), number=el('input'), range=el('input');
      number.type='number';number.id=inputId;number.setAttribute('aria-label',control.label||control.id);
      range.type='range';range.id=inputId+'-range';range.setAttribute('aria-label',t('review.control.slider',{label:control.label||control.id}));
      for(const input of [number,range]) {input.min=control.min;input.max=control.max;input.step=control.step;input.value=state.values[control.id];}
      const update=input=>{
        const value=Number(input.value);
        if(input.value===''||!Number.isFinite(value)||!input.checkValidity()) {clearSurfacePoints();clearTimeout(debounceTimer);state.previewSeq++;state.previewBusy=false;state.previewValid=false;status('review.control.rangeError',true,{min:control.min,max:control.max,step:control.step,unit:control.unit||''});updateLocks();updatePosition();return;}
        number.value=value;range.value=value;globalThis.ObjectAnimationInteractions?.refreshRanges(range);changeValue(control.id,value);
      };
      number.addEventListener('input',()=>update(number));range.addEventListener('input',()=>update(range));
      numberWrap.append(number,el('span','',control.unit||''));top.append(numberWrap);wrapper.append(range);
      const limits=el('div','control-limits');limits.append(el('span','',`${numberText(control.min)}${control.unit||''}`),el('span','',`${numberText(control.max)}${control.unit||''}`));wrapper.append(limits);
    } else if(control.kind==='color') {
      const row=el('div','color-row'),input=el('input'),value=el('span','color-value',state.values[control.id]);
      input.type='color';input.id=inputId;input.value=state.values[control.id];input.setAttribute('aria-label',control.label||control.id);
      input.addEventListener('input',()=>{value.textContent=input.value;changeValue(control.id,input.value);});row.append(input,value);top.append(row);
    } else if(control.kind==='choice') {
      const select=el('select');select.id=inputId;select.setAttribute('aria-label',control.label||control.id);
      for(const [index,option] of (control.options||[]).entries()) {const node=el('option','',option.label||String(option.value));node.value=String(index);node.selected=option.value===state.values[control.id];select.append(node);}
      select.addEventListener('change',()=>changeValue(control.id,control.options[Number(select.value)].value));wrapper.append(select);
    }
    if(control.description||control.help) wrapper.append(el('p','control-help',control.description||control.help));
    box.append(wrapper);
  }
  updateLocks();
}
function updateLocks() {
  const lock=!editable();
  for(const input of $('controls').querySelectorAll('input,select,button')) input.disabled=lock;
  $('reset-btn').disabled=lock;
  $('feedback-note').disabled=lock;
  $('confirm-btn').disabled=lock||!state.previewValid||state.previewBusy;
  $('revise-btn').disabled=lock||!state.previewValid||state.previewBusy;
  $('compare-btn').disabled=!state.base||!state.candidate||state.nativeBusy;
  $('clear-annotation').disabled=lock;
  $('reference-surface').setAttribute('aria-disabled',String(lock));$('reference-surface').tabIndex=lock?-1:0;
  renderInspection();
}
function changeValue(id,value) {
  if(!editable()) return;
  clearSurfacePoints();updatePosition();
  state.values[id]=value;state.previewValid=false;state.previewSeq++;
  state.compare=false;renderCompare();
  stopPlayback();status('review.status.updating');updateLocks();clearTimeout(debounceTimer);
  debounceTimer=setTimeout(()=>previewCandidate(),140);
}
function resetValues() {
  if(!editable()) return;
  clearSurfacePoints();state.values=clone(state.defaults);state.compare=false;updatePosition();renderControls();renderCompare();
  return previewCandidate();
}
async function toggleComparison() {
  stopPlayback();clearSurfacePoints();state.compare=!state.compare;updatePosition();
  try {await displayProject(false);clearSurfacePoints();updatePosition();renderCompare();} catch(error) {showError(error);}
}
async function previewCandidate() {
  clearTimeout(debounceTimer);
  if(!request()||state.stale) return;
  const seq=++state.previewSeq, requestId=request().id;
  state.previewBusy=true;state.previewValid=false;updateLocks();
  try {
    const result=await api('/api/review/preview',{...identity(),values:clone(state.values)});
    if(seq!==state.previewSeq||requestId!==request()?.id) return;
    state.candidate=result.project;state.values=result.values||state.values;
    await displayProject(false,seq);
    if(seq!==state.previewSeq||requestId!==request()?.id) return;
    state.previewValid=true;status('review.status.updated');clearError();
  } catch(error) {
    if(seq!==state.previewSeq) return;
    state.previewValid=false;showError(error);
  } finally {if(seq===state.previewSeq) {state.previewBusy=false;updateLocks();}}
}
async function displayProject(resetView=false,previewSeq=null) {
  if(!viewport||!state.current) return;
  const seq=++state.viewSeq,project=state.compare?state.base:state.candidate||state.base||state.current.project;
  if(stage()==='delivery') {await loadPlan(state.base||project,seq);if(seq===state.viewSeq)renderMedia();return;}
  await viewport.setProject(clone(project),{nativePreview:state.current.preview,preserveView:!resetView});
  if(seq!==state.viewSeq||(previewSeq!==null&&previewSeq!==state.previewSeq)) return;
  viewport.setInteraction({editable:false,helpers:false});viewport.setGrid(false);
  await loadPlan(project,seq);
  if(seq!==state.viewSeq) return;
  viewport.setFrame(state.frame);
  viewport.setCamera(state.freeView?null:reviewCamera());
  viewport.select(state.annotation?.object_id||activeCheckpoint()?.object_ids?.[0]||null);
  syncInspection();
  $('loading-overlay').hidden=!!(!project.source||state.current.preview);
  updatePosition();renderCompare();
}
async function loadPlan(project,viewSeq) {
  const fps=project.render?.fps||24;
  const shotId=request()?.focus?.shot_id||project.shots?.[0]?.id;
  const range=sourceRange();
  let fullFrames=[];
  if(shotId && (stage()==='motion'||stage()==='delivery')) {
    const result=await api('/api/plan',{project,shot:shotId,path:state.current.path});
    fullFrames=result.sourceFrames||[];
  }
  if(!fullFrames.length) fullFrames=Array.from({length:Math.max(1,Math.floor(range[1]-range[0]+1))},(_,i)=>range[0]+i);
  if(viewSeq!==state.viewSeq) return;
  state.fps=fps;
  state.fullFrames=fullFrames;
  state.frames=fullFrames.filter(frame=>frame>=range[0]&&frame<=range[1]);
  if(!state.frames.length) state.frames=[range[0]];
  state.index=closestIndex(state.frames,state.frame);
  if(!activeCheckpoint()&&!activeFinding()&&!(state.annotation?.source_frame===state.frame&&!editable())) state.frame=state.frames[state.index];
  $('frame-slider').max=state.frames.length-1;$('frame-slider').min=0;
  updateRangeLabels();
  updatePosition();
}
function updateRangeLabels() {$('range-start').textContent=t('review.start');$('range-end').textContent=secondsText(state.frames.length/state.fps);}
function closestIndex(frames,value) {
  let index=0,distance=Infinity;
  for(let i=0;i<frames.length;i++) if(Math.abs(frames[i]-value)<distance) {distance=Math.abs(frames[i]-value);index=i;}
  return index;
}
function setIndex(index) {
  const previous=state.frame;
  state.index=Math.max(0,Math.min(state.frames.length-1,Math.round(index)));state.frame=state.frames[state.index];
  if(state.frame!==previous) {
    state.checkpointId=null;state.findingId=null;clearSurfacePoints();
    if(editable()) {state.annotation=null;viewport?.select(null);}
  }
  viewport?.setFrame(state.frame);updatePosition();
}
function setFrameNearest(frame) {stopPlayback();setIndex(closestIndex(state.frames,frame));}
function updatePosition() {
  $('frame-slider').value=state.index;
  globalThis.ObjectAnimationInteractions?.refreshRanges($('frame-slider'));
  $('frame-label').textContent=secondsText(state.index/state.fps);
  $('frame-label').title=t('review.sourceFrame',{frame:frameText(state.frame)});
  $('frame-slider').title=t('review.sourceFrame',{frame:frameText(state.frame)});
  $('frame-slider').setAttribute('aria-valuetext',secondsText(state.index/state.fps));
  const id=state.annotation?.object_id||activeCheckpoint()?.object_ids?.[0]||focusedObject(),segment=currentSegment();
  for(const button of $('segments').querySelectorAll('[data-segment-id]')) button.setAttribute('aria-current',button.dataset.segmentId===segment?.id?'step':'false');
  let focusText=id?objectLabel(id):'';
  if(state.annotation) focusText='';
  else if(activeCheckpoint()) focusText='';
  else if(stage()==='delivery') focusText=state.review?.media_url?secondsText(Number($('review-video').currentTime)||0):t('review.waitingOutput');
  $('focus-label').textContent=focusText;
  $('focus-label').title=[id||'',segment?.title||'',t('review.sourceFrame',{frame:frameText(state.frame)})].filter(Boolean).join(' / ');
  $('clear-annotation').hidden=!state.annotation||!editable();
  $('annotation').hidden=!state.annotation;
  if(state.annotation) $('annotation').textContent=annotationText(state.annotation);
  updateCheckpointTabs();updateFindingTabs();updateReferenceMark();renderInspection();
}
function selectObject(id) {
  if(!editable()||!id||stage()==='delivery') return;
  if(request()?.inspection&&!inspectionIds().includes(id)) return;
  stopPlayback();
  const previous=state.annotation?.source_frame===state.frame?state.annotation:{};
  state.annotation={...previous,...locationAnnotation(),object_id:id};
  if(!activeCheckpoint()) delete state.annotation.checkpoint_id;
  viewport.select(id);updatePosition();
}
function updatePlaybackButton() {
  const button=$('play-btn'),label=state.playing?t('review.pausePlayback'):t('review.playSegment');
  button.setAttribute('aria-label',label);button.title=label;button.setAttribute('aria-pressed',String(state.playing));button.classList.toggle('is-playing',state.playing);
}
function stopPlayback() {state.playing=false;updatePlaybackButton();}
function togglePlayback() {
  if(stage()!=='motion') return;
  if(state.playing) {stopPlayback();return;}
  state.playing=true;state.playStart=performance.now();state.playIndex=state.index>=state.frames.length-1?0:state.index;
  updatePlaybackButton();requestAnimationFrame(playTick);
}
function playTick(time) {
  if(!state.playing) return;
  const index=state.playIndex+Math.floor((time-state.playStart)/1000*state.fps);
  if(index>=state.frames.length) {setIndex(state.frames.length-1);stopPlayback();return;}
  setIndex(index);requestAnimationFrame(playTick);
}
function renderCompare() {
  updateFindingEvidence();
  const compare=$('compare-btn'),compareLabel=state.compare?t('review.viewAdjusted'):t('review.compareOriginal');
  compare.setAttribute('aria-pressed',String(state.compare));compare.setAttribute('aria-label',compareLabel);compare.title=compareLabel;compare.classList.toggle('is-active',state.compare);
  $('compare-label').hidden=!state.compare;
  const orbit=$('orbit-btn'),orbitLabel=state.freeView?t('review.specifiedView'):t('review.orbitView');
  orbit.setAttribute('aria-pressed',String(state.freeView));orbit.setAttribute('aria-label',orbitLabel);orbit.title=orbitLabel;orbit.classList.toggle('is-active',state.freeView);
}
async function focusView() {
  if(activeFinding()) {selectFinding(activeFinding());return;}
  if(activeCheckpoint()) {selectCheckpoint(activeCheckpoint());return;}
  stopPlayback();state.freeView=stage()==='model'||!request();state.annotation=null;
  state.checkpointId=null;state.findingId=null;state.reviewCameraId=null;clearSurfacePoints();
  state.frame=request()?.focus?.source_frame||sourceRange()[0];
  await displayProject(true);
}
function renderMedia() {
  const delivery=stage()==='delivery';$('viewport').hidden=delivery;$('media-panel').hidden=!delivery;
  if(!delivery) {$('review-video').pause();return;}
  const media=request()?.media||{},url=state.review?.media_url;
  const image=media.type==='image'||media.kind==='image'||/\.(png|jpe?g|webp)$/i.test(media.path||'');
  $('media-empty').hidden=!!url;$('review-image').hidden=!url||!image;$('review-video').hidden=!url||image;
  if(url) {
    const node=image?$('review-image'):$('review-video');
    if(node.getAttribute('src')!==url) node.setAttribute('src',url);
  }
  $('loading-overlay').hidden=true;updatePosition();
}
function markVideoPosition() {
  if(!editable()||stage()!=='delivery') return;
  const index=Math.max(0,Math.min(state.fullFrames.length-1,Math.floor($('review-video').currentTime*state.fps)));
  const nextFrame=state.fullFrames[index]??request()?.focus?.source_frame??1;
  if(nextFrame!==state.frame) {state.checkpointId=null;state.annotation=null;}
  state.frame=nextFrame;
  state.annotation={...(state.annotation||{}),...locationAnnotation()};updatePosition();
}

function renderReceipt(force=false) {
  const review=state.review,submitted=!!review&&review.status!=='pending';
  $('adjustments').hidden=submitted||!(request()?.controls?.length);
  renderConnection();
  const signature=JSON.stringify({request:review?.request,status:review?.status,response:review?.response,message:review?.message,agent_listening:review?.agent_listening,defaults:state.defaults,stale:state.stale});
  if(!force&&signature===receiptSignature) {updateLocks();return;}
  receiptSignature=signature;
  $('feedback-card').hidden=!review||submitted||state.stale;
  $('receipt').hidden=!submitted;
  $('waiting-card').hidden=!!review;
  if(!review) return;
  if(!submitted) return;
  const response=review.response||{};
  let title=t('review.feedbackSaved'),description;
  if(review.status==='applied') {title=request().controls?.length?t('review.receipt.appliedTitle'):t('review.receipt.confirmedTitle');description=request().controls?.length?t('review.receipt.appliedDescription'):t('review.receipt.confirmedDescription');}
  else if(review.status==='closed') {title=t('review.receipt.closedTitle');description=t('review.receipt.closedDescription');}
  else if(review.status==='superseded') {title=t('review.receipt.supersededTitle');description=t('review.receipt.supersededDescription');}
  else if(response.received_at && response.received_by_thread) {title=t('review.receipt.readTitle');description=t('review.receipt.readDescription');}
  else if(review.agent_listening) {description=t('review.receipt.listeningDescription');}
  else {description=t('review.receipt.returnDescription');}
  $('receipt-title').textContent=title;$('receipt-description').textContent=description;
  const values=response.values||review.values||{},lines=$('receipt-values');lines.replaceChildren();
  for(const control of request().controls||[]) {
    const row=el('div','receipt-line'),before=state.defaults[control.id],after=values[control.id];
    row.append(el('span','',control.label||control.id),el('strong','',before===after?formatValue(control,after):`${formatValue(control,before)} → ${formatValue(control,after)}`));lines.append(row);
  }
  if(response.decision) {const row=el('div','receipt-line');row.append(el('span','',t('review.receipt.yourChoice')),el('strong','',response.decision==='confirm'?t('review.receipt.confirmChoice'):t('review.receipt.reviseChoice')));lines.append(row);}
  if(response.annotation) {const row=el('div','receipt-line receipt-location');row.append(el('span','',t('review.receipt.location')),el('strong','',annotationText(response.annotation)));lines.append(row);}
  $('receipt-note').textContent=response.note||'';$('receipt-note').hidden=!response.note;
  const internalMessages=['Agent created a newer review request','Feedback saved; waiting for the agent to process it','Agent applied the confirmed adjustment','Agent closed this review','Agent received the feedback; no project change has been applied yet'];
  const message=internalMessages.includes(review.message)?'':review.message||'';
  $('agent-message').textContent=message;$('agent-message').hidden=!message;
  $('return-actions').hidden=review.status==='applied'||review.status==='closed';
  const threadId=request().thread_id;
  $('thread-link').hidden=!threadId;
  if(threadId) $('thread-link').href='codex://threads/'+encodeURIComponent(threadId);
  updateLocks();
}
function feedbackText() {
  const response=state.review?.response;
  return t('review.feedback.template',{title:request()?.title||t('review.animationPreview'),request:request()?.id||'',decision:t(response?.decision==='revise'?'review.receipt.reviseChoice':'review.receipt.confirmChoice'),location:response?.annotation?t('review.feedback.locationLine',{location:annotationText(response.annotation)}):'',note:response?.note?t('review.feedback.noteLine',{note:response.note}):''});
}
async function copyFeedback() {
  const text=feedbackText();
  try {await navigator.clipboard.writeText(text);toast('review.feedback.copied');}
  catch {$('copy-fallback').value=text;$('copy-fallback').hidden=false;$('copy-fallback').focus();$('copy-fallback').select();toast('review.feedback.copyManually');}
}
async function submit(decision) {
  if(!editable()||!state.previewValid||state.previewBusy) return;
  const note=$('feedback-note').value.trim();
  if(decision==='revise'&&!note) {revealFeedback(true);return;}
  stopPlayback();
  if(stage()==='delivery'&&state.review.media_url&&!$('review-video').hidden) {$('review-video').pause();markVideoPosition();}
  state.submitBusy=true;updateLocks();
  try {
    const body={...identity(),values:clone(state.values),decision,note};
    const annotation=state.annotation||((activeCheckpoint()||state.referenceId)?locationAnnotation():null);
    if(annotation) {
      body.annotation=clone(annotation);
      if(body.annotation.checkpoint_id&&!checkpoints().some(item=>item.id===body.annotation.checkpoint_id&&item.source_frame===body.annotation.source_frame&&(!body.annotation.reference_id||item.reference_id===body.annotation.reference_id))) delete body.annotation.checkpoint_id;
    }
    const result=await api('/api/review/submit',body);
    await acceptReview(result,false);setInspector(true);toast('review.feedbackSaved');
    $('receipt').scrollIntoView({behavior:'smooth',block:'nearest'});
  } catch(error) {showError(error);}
  finally {state.submitBusy=false;updateLocks();}
}

async function prepareNative() {
  if(!state.current?.project?.source||state.current.preview||state.nativeBusy) return;
  state.nativeBusy=true;const path=state.current.path,revision=state.current.revision;
  $('loading-overlay').hidden=false;loadingText('review.loadingNative');updateLocks();
  try {
    let job=await api('/api/job',{operation:'native-preview',path,revision});
    while(job.status==='queued'||job.status==='running') {await new Promise(resolve=>setTimeout(resolve,900));job=await api('/api/job?id='+encodeURIComponent(job.id));}
    if(job.status==='failed') throw (job.error?new Error(job.error):uiError('review.error.nativePreview'));
    if(path!==state.current.path) return;
    const current=await api('/api/project');
    if(current.path!==path) return;
    state.current.preview=current.preview||job.result;state.current.manifest=current.manifest||state.current.preview?.manifest;
    await displayProject(true);
  } catch(error) {showError(error);loadingText('review.nativeIncomplete');}
  finally {state.nativeBusy=false;updateLocks();}
}
async function acceptReview(data,force=false) {
  const next=data.review??null,current=data.current||state.current;
  if(!current) throw uiError('review.error.noProject');
  const newRequest=force||next?.request?.id!==state.review?.request?.id||current.path!==state.current?.path;
  const statusChanged=next?.status!==state.review?.status;
  const appliedChanged=next?.applied_revision!==state.review?.applied_revision;
  const revisionChanged=current.revision!==state.current?.revision;
  state.current=current;state.review=next;
  state.stale=!!linkRequest&&linkRequest!==next?.request?.id;
  if(newRequest) {
    stopPlayback();clearTimeout(debounceTimer);state.previewSeq++;state.viewSeq++;
    state.base=clone(next?.baseline_project||current.project);state.candidate=clone(next?.status==='applied'||next?.status==='closed'?current.project:state.base);
    state.defaults=Object.fromEntries((next?.request?.controls||[]).map(control=>[control.id,control.value]));
    state.values=clone(next?.response?.values||next?.values||state.defaults);
    state.annotation=next?.response?.annotation?clone(next.response.annotation):null;state.compare=false;state.previewValid=false;state.previewBusy=false;
    state.findingId=state.annotation?.finding_id||null;state.inspectionTool=null;state.isolate=false;state.xray=false;
    state.freeView=stage()==='model'||!next;state.frame=state.annotation?.source_frame??next?.request?.focus?.source_frame??sourceRange()[0];
    const initialCheckpoint=checkpoints().find(item=>item.id===state.annotation?.checkpoint_id)||checkpoints().find(item=>item.source_frame===state.frame);
    const initialFinding=findings().find(item=>item.id===state.findingId);
    state.referenceId=state.annotation?.reference_id||initialFinding?.reference_id||initialCheckpoint?.reference_id||references()[0]?.id||null;
    state.referenceOpen=references().length>0;state.checkpointId=initialFinding?null:initialCheckpoint?.id||null;state.reviewCameraId=initialFinding?.camera_id||initialCheckpoint?.camera_id||null;
    if(initialFinding||initialCheckpoint) {state.frame=(initialFinding||initialCheckpoint).source_frame;state.freeView=false;}
    if(!state.annotation&&initialCheckpoint&&editable()) state.annotation=locationAnnotation();
    $('feedback-note').value='';$('copy-fallback').hidden=true;
    if($('feedback-details')) $('feedback-details').open=false;
    if($('task-details')) $('task-details').open=false;
    if(['submitted','applied','closed'].includes(next?.status)) setInspector(true);
    clearError();
    renderHeader();renderControls();renderReceipt();renderMedia();
    await displayProject(true);
    if(next&&!state.stale&&['pending','submitted'].includes(next.status)) await previewCandidate();
    else {state.previewValid=!state.stale;updateLocks();}
    if(stage()!=='delivery') prepareNative();
  } else {
    if(statusChanged&&next?.response?.annotation) {state.annotation=clone(next.response.annotation);updatePosition();}
    renderConnection();renderReceipt();
    if(statusChanged||appliedChanged||(revisionChanged&&next?.status==='applied')) {
      clearTimeout(debounceTimer);state.previewSeq++;state.previewBusy=false;
      if(next?.response?.values) state.values=clone(next.response.values);
      renderControls();
      if(next.status==='applied') {state.candidate=clone(current.project);await displayProject(false);}
      else if(next.status==='submitted'&&!state.stale) await previewCandidate();
    } else if(revisionChanged&&next?.status==='pending') {
      state.previewValid=false;status('review.status.projectChanged',true);updateLocks();
    }
    if(stage()==='delivery') renderMedia();
  }
}
async function pollReview() {
  if(state.pollBusy) return;
  state.pollBusy=true;
  try {await acceptReview(await api('/api/review'));}
  catch(error) {connectionStatus('review.connection.interrupted');}
  finally {state.pollBusy=false;pollTimer=setTimeout(pollReview,2000);}
}
function setup() {
  const locationRow=el('div','annotation-row');$('annotation').before(locationRow);locationRow.append($('annotation'),$('clear-annotation'));
  setInspector(!window.matchMedia('(max-width: 739px)').matches);
  $('inspector-toggle')?.addEventListener('click',()=>setInspector($('workspace').dataset.inspector!=='open'));
  $('jump-controls').addEventListener('click',event=>{
    event.preventDefault();setInspector(true);
    requestAnimationFrame(()=>{
      const panel=$('adjustment-panel');
      const target=[...panel.querySelectorAll('input:not(:disabled),select:not(:disabled),button:not(:disabled),textarea:not(:disabled)')].find(node=>node.getClientRects().length);
      (target||panel).focus();
    });
  });
  document.addEventListener('click',event=>{
    const details=$('task-details');
    if(details?.open&&!details.contains(event.target)) details.open=false;
  });
  document.addEventListener('keydown',event=>{
    if(event.key!=='Escape'||event.isComposing) return;
    const details=$('task-details');
    if(details?.open) {details.open=false;details.querySelector('summary')?.focus();}
    if(window.matchMedia('(max-width: 739px)').matches&&$('workspace').dataset.inspector==='open') {setInspector(false);$('inspector-toggle')?.focus();}
  });
  viewport=new Viewport($('viewport'),{onSelect:selectObject,onSurfacePick:selectSurface,onInspectionMiss:handleInspectionMiss,onInspectionHover:handleInspectionHover});viewport.setInteraction({editable:false,helpers:false});viewport.setGrid(false);
  viewport.renderer.domElement.setAttribute('aria-label',t('review.viewportInstructions'));
  viewport.renderer.domElement.setAttribute('aria-describedby','inspection-hint');
  // The persistent step hint announces both progress and distance in review.
  viewport.measurementLabel?.setAttribute('aria-live','off');
  $('frame-slider').addEventListener('input',()=>{stopPlayback();setIndex(Number($('frame-slider').value));});
  $('play-btn').addEventListener('click',togglePlayback);
  $('focus-btn').addEventListener('click',()=>focusView().catch(showError));
  $('orbit-btn').addEventListener('click',()=>{state.freeView=!state.freeView;viewport.setCamera(state.freeView?null:reviewCamera());if(state.freeView)viewport.frameAll();renderCompare();});
  $('compare-btn').addEventListener('click',toggleComparison);
  $('reset-btn').addEventListener('click',resetValues);
  $('clear-annotation').addEventListener('click',()=>{if(editable())clearAnnotation();});
  $('reference-toggle').addEventListener('click',()=>{state.referenceOpen=!state.referenceOpen;renderReference();});
  $('checkpoints').addEventListener('keydown',event=>keyboardTabs(event,$('checkpoints')));
  $('findings').addEventListener('keydown',event=>keyboardTabs(event,$('findings')));
  for(const button of $('inspection-tools').querySelectorAll('[data-inspection-tool]')) button.addEventListener('click',()=>toggleInspection(button.dataset.inspectionTool));
  $('inspection-restart')?.addEventListener('click',restartMeasurement);
  $('inspection-snap')?.addEventListener('click',toggleInspectionSnap);
  $('inspection-tools').addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const buttons=[...$('inspection-tools').querySelectorAll('button:not([hidden]):not(:disabled)')],index=buttons.indexOf(event.target);
    if(index<0) return;event.preventDefault();
    buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length].focus();
  });
  viewport.renderer.domElement.addEventListener('keydown',event=>{
    if(event.key==='Escape') {state.inspectionTool=null;clearSurfacePoints();syncInspection();updatePosition();}
  });
  $('reference-tabs').addEventListener('keydown',event=>keyboardTabs(event,$('reference-tabs')));
  $('reference-surface').addEventListener('click',referenceClick);
  $('reference-surface').addEventListener('keydown',referenceKey);
  $('reference-image').addEventListener('load',()=>{$('reference-error').hidden=true;updateReferenceMark();});
  $('reference-image').addEventListener('error',()=>{$('reference-image').hidden=true;$('reference-mark').hidden=true;$('reference-error').hidden=false;});
  referenceObserver=new ResizeObserver(updateReferenceMark);referenceObserver.observe($('reference-surface'));
  $('confirm-btn').addEventListener('click',()=>submit('confirm'));
  $('revise-btn').addEventListener('click',()=>submit('revise'));
  $('copy-feedback').addEventListener('click',copyFeedback);
  $('review-video').addEventListener('pause',markVideoPosition);
  $('review-video').addEventListener('seeked',markVideoPosition);
  $('review-video').addEventListener('timeupdate',updatePosition);
  $('review-video').addEventListener('error',()=>showError(uiError('review.error.video')));
  $('review-image').addEventListener('error',()=>showError(uiError('review.error.image')));
  window.addEventListener('beforeunload',()=>{clearTimeout(pollTimer);stopPlayback();referenceObserver?.disconnect();viewport.dispose();});
  refreshLocale();
}
// Locale changes repaint product text in place. No project, playback, camera,
// input, annotation, evidence, or review-request state is recreated here.
function refreshLocale() {
  const savedConnection=connectionKey;
  renderHeader(false);
  for(const button of $('checkpoints').querySelectorAll('[data-checkpoint-id]')) {
    const checkpoint=checkpoints().find(item=>item.id===button.dataset.checkpointId);
    if(checkpoint) button.title=t('review.checkpointTitle',{title:checkpoint.title||checkpoint.id,frame:frameText(checkpoint.source_frame)});
  }
  for(const button of $('findings').querySelectorAll('[data-finding-id]')) {
    const finding=findings().find(item=>item.id===button.dataset.findingId);
    if(finding) updateFindingLabel(button,finding);
  }
  for(const [index,number] of [...$('segments').querySelectorAll('.segment-number')].entries()) number.textContent=numberText(index+1,{minimumIntegerDigits:2,useGrouping:false});
  for(const wrapper of $('controls').querySelectorAll('[data-control]')) {
    const control=request()?.controls?.find(item=>item.id===wrapper.dataset.control);
    if(control?.kind!=='number') continue;
    wrapper.querySelector('input[type=range]')?.setAttribute('aria-label',t('review.control.slider',{label:control.label||control.id}));
    const limits=wrapper.querySelectorAll('.control-limits span');
    if(limits[0]) limits[0].textContent=numberText(control.min)+(control.unit||'');
    if(limits[1]) limits[1].textContent=numberText(control.max)+(control.unit||'');
  }
  renderReference();renderCompare();updatePlaybackButton();updateRangeLabels();updatePosition();renderReceipt(true);
  viewport?.renderer.domElement.setAttribute('aria-label',t('review.viewportInstructions'));
  if(statusMessage) $('preview-status').textContent=messageText(statusMessage);
  if(lastError) $('error-banner').textContent=errorText(lastError);
  if(toastMessage) $('toast').textContent=t(toastMessage.key,toastMessage.params);
  $('loading-text').textContent=t(loadingKey);
  if(!$('copy-fallback').hidden) {
    const node=$('copy-fallback'),start=node.selectionStart,end=node.selectionEnd,direction=node.selectionDirection;
    node.value=feedbackText();node.setSelectionRange(start,end,direction);
  }
  connectionStatus(savedConnection);
}
onLocaleChange(refreshLocale);

async function boot() {
  try {setup();const session=await api('/api/session');state.token=session.token;await acceptReview(await api('/api/review'),true);pollTimer=setTimeout(pollReview,2000);}
  catch(error) {showError(error);$('loading-overlay').hidden=true;connectionStatus('review.connection.notConnected');}
}
boot();
