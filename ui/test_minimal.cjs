const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=fs.readFileSync(__dirname+'/minimal.js','utf8');
let messages=[],requests=[],fields={};
const context={AbortSignal,URL,URLSearchParams,FormData,console,
  document:{getElementById:id=>id==='notice'?{set textContent(v){messages.push(v);}}:id==='main_link'?{href:'http://device/key/'}:fields[id],querySelector:()=>({content:'nonce'}),addEventListener:()=>{}},
  fetch:async(url,options)=>{requests.push({url,options});return{ok:true,status:200,json:async()=>({'710':{status:1}})};}};
vm.createContext(context);vm.runInContext(script,context);
(async()=>{
  fields['value710-0']={value:'21.5'};
  await context.set(710,0);
  assert.equal(requests[0].url,'http://device/key/JS');
  assert.equal(requests[0].options.method,'POST');
  assert.equal(requests[0].options.headers['X-BSB-Token'],'nonce');
  assert.deepEqual(JSON.parse(requests[0].options.body),[{parameter:710,value:'21.5',type:1,destination:0}]);
  fields['value5020-10']={selectedOptions:[{value:'1'},{value:'4'}]};
  await context.setbit(5020,10);
  assert.deepEqual(JSON.parse(requests[1].options.body),[{parameter:5020,value:'5',type:1,destination:10}]);
  context.fetch=async()=>({ok:true,status:200,json:async()=>({'710':{status:0}})});
  await context.set(710,0);assert.match(messages.at(-1),/did not accept/);
  context.fetch=async()=>{throw Object.assign(new Error('timeout'),{name:'TimeoutError'});};
  await context.set(710,0);assert.match(messages.at(-1),/Read the value before retrying/);
  let release;context.fetch=()=>new Promise(r=>{release=r;});
  const first=context.command('CI','option_1=1','application/x-www-form-urlencoded');
  await assert.rejects(context.command('CI','option_1=1'),/current request/);
  release({ok:true});await first;
  console.log('5 minimal control checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
