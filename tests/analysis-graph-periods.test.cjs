const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.resolve(__dirname,'../static/js/analysis-graph.js'),'utf8');
function setup(days=1) {
  const buttons=[1,3,7,30].map(d=>({active:d===days,getAttribute:()=>String(d),setAttribute(k,v){this[k]=v;},classList:{toggle(){}}}));
  const ctx={window:{},document:{addEventListener(){},documentElement:{getAttribute:()=> 'light'}},URLSearchParams,console,requestAnimationFrame(){},cancelAnimationFrame(){},clearTimeout(){}};
  vm.createContext(ctx);
  vm.runInContext(source.replace('window.AnalysisGraphV2 = {','window.__graphTest = {state,ui,buildGraphParams,applyGraphTimeRange,selectPeriod,loadDynamicWindow,refresh};\n  window.AnalysisGraphV2 = {'),ctx);
  const graph=ctx.window.__graphTest;
  graph.ui.period={querySelector:()=>buttons.find(b=>b.active),querySelectorAll:()=>buttons};
  graph.ui.fsPeriod={querySelectorAll:()=>buttons};
  // Class updates are shared by both normal and full-screen period controls.
  buttons.forEach(b=>b.classList.toggle=(name,on)=>b.active=on);
  graph.ui.start={value:''};graph.ui.end={value:''};
  return {ctx,graph,buttons};
}
for(const days of [1,3,7,30])test('preset '+days+' days loads the full range even with an automatic timeline bucket',()=>{
  const {graph}=setup(days);
  graph.state.timelineBuckets=[{sessions:5,active_ids:3}];graph.state.selectedBucketRange={start:'2026-09-13 10:00:00',end:'2026-09-13 11:00:00'};
  const params=graph.buildGraphParams();assert.equal(graph.applyGraphTimeRange(params),'days');
  assert.equal(params.get('days'),String(days));assert.equal(params.has('minutes'),false);assert.equal(params.has('start'),false);
});
test('manual empty timeline interval is preserved instead of silently expanding',()=>{
  const {graph}=setup(7);graph.state.timelineManual=true;graph.state.selectedBucketRange={start:'2026-09-13 10:00:00',end:'2026-09-13 11:00:00'};
  const params=graph.buildGraphParams();assert.equal(graph.applyGraphTimeRange(params),'bucket');assert.equal(params.get('start'),graph.state.selectedBucketRange.start);assert.equal(params.has('days'),false);
});
test('custom dates remain available in advanced filters',()=>{
  const {graph}=setup();graph.ui.start.value='2026-09-01T00:00';graph.ui.end.value='2026-09-03T00:00';
  const params=graph.buildGraphParams();assert.equal(graph.applyGraphTimeRange(params),'custom');assert.equal(params.get('start'),'2026-09-01T00:00');assert.equal(params.has('days'),false);
});
test('preset clears old dates and manual selection and synchronizes both controls',()=>{
  const {graph,buttons}=setup();graph.ui.start.value='2026-09-01T00:00';graph.ui.end.value='2026-09-03T00:00';graph.ui.fsStart={value:'old'};graph.ui.fsEnd={value:'old'};
  graph.state.timelineManual=true;graph.state.selectedBucketRange={start:'old',end:'old'};
  graph.selectPeriod('30');assert.equal(graph.ui.start.value,'');assert.equal(graph.ui.fsEnd.value,'');assert.equal(graph.state.timelineManual,false);assert.equal(graph.state.selectedBucketRange,null);assert.equal(buttons.find(b=>b.active).getAttribute(),'30');
});
test('live full-period graph uses the aggregate endpoint with selected days',async()=>{
  const {graph,ctx}=setup(30);let request;
  ctx.fetch=async(url)=>{request=url;return {ok:true,json:async()=>({nodes:[],edges:[]})};};
  await graph.loadDynamicWindow();const url=new URL(request,'http://localhost');assert.equal(url.pathname,'/api/analysis/graph');assert.equal(url.searchParams.get('days'),'30');assert.equal(url.searchParams.has('minutes'),false);
});
test('manual dynamic interval uses its actual duration',async()=>{
  const {graph,ctx}=setup();let request;graph.state.timelineManual=true;graph.state.selectedBucketRange={start:'2026-09-13 10:00:00',end:'2026-09-13 10:05:00'};graph.state.timelineBuckets=[graph.state.selectedBucketRange];
  ctx.fetch=async(url)=>{request=url;return {ok:true,json:async()=>({nodes:[],edges:[]})};};await graph.loadDynamicWindow();const url=new URL(request,'http://localhost');assert.equal(url.pathname,'/api/analysis/graph-dynamic/window');assert.equal(url.searchParams.get('window_minutes'),'5');
});
test('period change during an active request is queued for another refresh',async()=>{
  const {graph}=setup();graph.state.active=true;graph.state.loading=true;await graph.refresh({animatePeriod:true});assert.equal(graph.state.queuedRefresh.animatePeriod,true);
});
