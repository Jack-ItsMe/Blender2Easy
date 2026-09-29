import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
let source=readFileSync(new URL('../../skills/blender2easy/editor/web/app.js',import.meta.url),'utf8').replace(/\r\n/g,'\n').replace(/^import .*;$/gm,'').replace(/\ninitPreferences\(\);\ntranslatePage\(\);\nonLocaleChange\(refreshLanguage\);\ninit\(\);\s*$/,'');
let toggles=0,prevented=0;
const dialog={open:false},play={click(){toggles++;}};
const document={activeElement:null,getElementById:id=>id==='workspace-dialog'?dialog:play};
const context={document,registerMessages(){},messages:{},console};
vm.createContext(context);vm.runInContext(source+';globalThis.shortcut=handleWorkspaceShortcut;',context);
const space=()=>({key:' ',code:'Space',ctrlKey:false,metaKey:false,defaultPrevented:false,preventDefault(){prevented++;}});
for(const tagName of ['BUTTON','SUMMARY','A']){
 document.activeElement={tagName,closest(){return this;}};context.shortcut(space());
 assert.equal(toggles,0);assert.equal(prevented,0,'Native button activation must remain possible');
}
for(const tagName of ['INPUT','TEXTAREA','SELECT']){document.activeElement={tagName};context.shortcut(space());assert.equal(toggles,0);}
document.activeElement={isContentEditable:true};context.shortcut(space());assert.equal(toggles,0);
document.activeElement={tagName:'CANVAS',closest(){return null;}};
dialog.open=true;context.shortcut(space());assert.equal(toggles,0);dialog.open=false;
context.shortcut({...space(),defaultPrevented:true});assert.equal(toggles,0);
context.shortcut(space());assert.equal(toggles,1);assert.equal(prevented,1);
console.log('PASS: focused buttons own Space; inputs, editable content and dialogs are protected; canvas Space still toggles playback');
