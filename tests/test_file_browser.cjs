// Minimal DOM contract tests; no browser session, cookies or school requests.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag='div') { this.tag = tag; this.children = []; this.textContent = ''; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  querySelectorAll(tag) { return this.children.flatMap(child => [
    ...(child.tag === tag ? [child] : []), ...child.querySelectorAll(tag)]); }
}
function browser() {
  const elements = new Map();
  const document = {
    getElementById(id) { if (!elements.has(id)) elements.set(id,new Element()); return elements.get(id); },
    createElement(tag) { return new Element(tag); }
  };
  const calls = [], window = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../onboarding/static/file-browser.js'),'utf8'),
    {document,window,URL,inspectTool:(name,args)=>calls.push({name,args})});
  return {view:window.classFileBrowser, elements, calls};
}
test('folder navigation is explicit and filenames are text, not HTML', () => {
  const {view,elements,calls} = browser();
  view.render({files:[{name:'<img onerror=bad>',url:'https://school.test/file.pdf',size_bytes:0}],
    folders:[{id:'7',name:'Resources',url:'https://school.test/folder/7'}],recursive:false});
  view.setBusy(false);
  assert.equal(calls.length,0);
  const link = elements.get('files-items').children[0].children[0];
  assert.equal(link.textContent,'<img onerror=bad>');
  assert.equal(link.rel,'noopener noreferrer');
  elements.get('files-folders').children[0].children[0].onclick();
  assert.equal(calls[0].args.folder_id,'7');
  view.render({folder_id:'7',files:[],folders:[],recursive:false});
  assert.equal(elements.get('files-up').disabled,false);
  elements.get('files-up').onclick();
  assert.equal(calls[1].args.folder_id,undefined);
});
test('unsafe links, failed requests and changing classes cannot leave stale listings', () => {
  const {view,elements} = browser();
  view.render({files:[{name:'Bad',url:'javascript:alert(1)'}],folders:[],recursive:false});
  assert.equal(elements.get('files-items').children[0].children[0].tag,'span');
  view.render({error:{message:'Access denied'}});
  assert.equal(elements.get('files-items').children.length,0);
  assert.equal(elements.get('files-location').textContent,'Access denied');
  view.reset();
  assert.equal(elements.get('files-root').disabled,true);
});
