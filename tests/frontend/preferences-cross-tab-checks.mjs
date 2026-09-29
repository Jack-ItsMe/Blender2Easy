import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';

const web=path.join(path.dirname(fileURLToPath(import.meta.url)),'../../skills/blender2easy/editor/web');
async function create({search='',saved={},denyStorage=false}={}) {
  const listeners=new Map(),storage=new Map(Object.entries(saved)),element={dataset:{},style:{}};
  const context=vm.createContext({URLSearchParams,Intl,navigator:{languages:['en-US']},location:{search},
    document:{documentElement:element,getElementById:()=>null,querySelectorAll:()=>[]},
    localStorage:{getItem:key=>{if(denyStorage)throw new Error('blocked');return storage.get(key)??null;},setItem:(key,value)=>{if(denyStorage)throw new Error('blocked');storage.set(key,value);}},
    addEventListener:(name,callback)=>listeners.set(name,callback),matchMedia:()=>({matches:false,addEventListener(){}})});
  const modules=new Map();
  async function load(filename) {
    filename=path.resolve(filename);
    if(!modules.has(filename))modules.set(filename,new vm.SourceTextModule(await readFile(filename,'utf8'),{context,identifier:filename}));
    return modules.get(filename);
  }
  const module=await load(path.join(web,'i18n.js'));
  await module.link((specifier,from)=>load(specifier.startsWith('/')?path.join(web,specifier.slice(1)):path.resolve(path.dirname(from.identifier),specifier)));
  await module.evaluate();
  module.namespace.initPreferences();
  return {i18n:module.namespace,listeners,storage,element};
}
const results=[];
const page=await create({search:'?lang=zh-Hant',saved:{'object-animation.language':'en','object-animation.theme':'dark'}});
assert.equal(page.i18n.getLocale(),'zh-Hant');
page.storage.set('object-animation.theme','light');
page.listeners.get('storage')({key:'object-animation.theme'});
results.push({check:'A cross-tab theme change preserves a page-specific URL language',expected:{locale:'zh-Hant',theme:'light'},actual:{locale:page.i18n.getLocale(),theme:page.i18n.getTheme()}});
const blocked=await create({denyStorage:true});
blocked.i18n.setLanguage('zh-Hant');blocked.i18n.setTheme('light');
results.push({check:'Blocked localStorage permits in-memory settings',expected:{locale:'zh-Hant',theme:'light'},actual:{locale:blocked.i18n.getLocale(),theme:blocked.i18n.getTheme()}});
for(const result of results)result.status=JSON.stringify(result.actual)===JSON.stringify(result.expected)?'PASS':'FAIL';
console.log(JSON.stringify(results,null,2));
if(results.some(result=>result.status==='FAIL'))process.exitCode=1;
