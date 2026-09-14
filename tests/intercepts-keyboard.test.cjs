const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
function setup(field, value) {
  const doc = {activeElement:null, querySelectorAll:()=>[]};
  const textarea = {id:field,value,disabled:false,selectionStart:value.length,selectionEnd:value.length,scrollTop:0,clientHeight:100,scrollHeight:100,setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;},focus(){doc.activeElement=this;}};
  doc.activeElement=textarea;
  const context = {document:doc, console, CAN_EDIT:true, ACTIVE_CLOSED:false, ACTIVE_ITEM_ID:1, ACTIVE_CATALOG_ID:0, ACTIVE_CAT:null,
    CORR_ID_SUGGEST_ENABLED:true, BLANK_AUTOSAVE_ENABLED:false, BLANK_VIEW_MODE:'plain',LAST_SAVED:value,
    SUGGEST:{open:false,items:[],idx:0,prefix:''},SUGGEST_INPUT:{open:false,items:[],idx:0,prefix:''},
    ALL_CALLSIGNS:[{label:'Береза',code:'1234'},{label:'Беркут',code:'1256'},{label:'Волна',code:'9876'}], CALLSIGNS:[], AUDIO_QUEUE:[],
    $:id=>id===field?textarea:null, requestAnimationFrame:fn=>fn(),scheduleTypingPing(){},updateSendButton(){},_currentAudioItem:()=>null};
  context.window=context;vm.createContext(context);
  for(const file of ['intercepts-preview.js','intercepts-callsigns.js','intercepts-blank.js']) {
    vm.runInContext(fs.readFileSync(path.join(root,'static/js',file),'utf8'),context,{filename:file});
  }
  const init=fs.readFileSync(path.join(root,'static/js/intercepts-init.js'),'utf8');
  // Execute the actual page keyboard listener with the production module scopes.
  const listener=init.match(/document\.addEventListener\("keydown", (\(ev\) => \{[\s\S]*?\n  \})\);/);
  assert.ok(listener,'page keyboard listener exists');
  context.keydown=vm.runInContext('('+listener[1]+')',context);
  const press=(key,extras={})=>{const event={key,prevented:false,preventDefault(){this.prevented=true;},...extras};context.keydown(event);return event;};
  return {context,textarea,press};
}
for(const field of ['intercept-text','intercept-input']) {
  test(field+': Enter adds dash at the cursor',()=>{
    const {textarea,press}=setup(field,'строка хвост');textarea.setSelectionRange(6,6);
    assert.equal(press('Enter').prevented,true);assert.equal(textarea.value,'строка\n- хвост');assert.equal(textarea.selectionStart,8);
  });
  test(field+': Shift+Enter and composing input keep browser behavior',()=>{
    const {textarea,press}=setup(field,'строка');
    assert.equal(press('Enter',{shiftKey:true}).prevented,false);
    assert.equal(press('Enter',{isComposing:true}).prevented,false);assert.equal(textarea.value,'строка');
  });
  for(const prefix of ['Бер','12']) test(field+': Tab accepts suggestion for '+prefix,()=>{
    const {context,textarea,press}=setup(field,'строка ('+prefix);
    context.updateSuggestFromCursor({key:'р'},field);
    const suggest=field==='intercept-text'?context.SUGGEST:context.SUGGEST_INPUT;
    assert.equal(suggest.open,true);assert.equal(suggest.items.length,2);
    press('ArrowDown');assert.equal(suggest.idx,1);
    const expected=suggest.items[1].code;
    assert.equal(press('Tab').prevented,true);assert.equal(textarea.value,'строка ('+expected+')');assert.equal(suggest.open,false);
  });
  test(field+': Enter accepts suggestion without adding a dash',()=>{
    const {context,textarea,press}=setup(field,'(987');context.updateSuggestFromCursor({},field);
    assert.equal(press('Enter').prevented,true);assert.equal(textarea.value,'(9876)');
  });
}
test('input: correspondent ID from the active audio item remains available',()=>{
  const {context,textarea,press}=setup('intercept-input','(55');
  context._currentAudioItem=()=>({correspondent_id:'FR_5566'});context.updateSuggestFromCursor({},'intercept-input');press('Tab');assert.equal(textarea.value,'(5566)');
});
test('input: Tab accepts a correspondent ID from the audio queue',()=>{
  const {context,textarea,press}=setup('intercept-input','(66');
  context.AUDIO_QUEUE=[{correspondent_id:'FR_6677'}];
  context.updateSuggestFromCursor({},'intercept-input');press('Tab');assert.equal(textarea.value,'(6677)');
});
test('audio: correspondent ID from a waveform segment remains available',()=>{
  const {context}=setup('intercept-input','');
  assert.equal(context._correspondentIdFromSegment({item:{correspondent_id:'FR_7788'}}),'7788');
  assert.equal(context._correspondentIdFromSegment({id:'FR-8899'}),'8899');
});
test('input: time header removes the dash and scrolling helper is callable',()=>{
  const {context,textarea}=setup('intercept-input','-12.17');
  context._fixDashIfTimeHeaderAtCursor('intercept-input',textarea);assert.equal(textarea.value,'12.17');
  context._autoScrollEditorIfNeeded(textarea);assert.equal(textarea.scrollTop,textarea.scrollHeight);
});
