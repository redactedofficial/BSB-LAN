'use strict';
const notice=message=>{document.getElementById('notice').textContent=message;};
const root=()=>document.getElementById('main_link').href;
let writing=false;
async function command(path,body,type='application/json'){
  if(writing)throw Error('Wait for the current request.');
  writing=true;
  try{
    const response=await fetch(root()+path,{method:'POST',headers:{'Content-Type':type,'X-BSB-Token':document.querySelector('meta[name=gateway-token]').content},body,signal:AbortSignal.timeout(60000)});
    if(!response.ok)throw Error('Request rejected ('+response.status+').');
    return response;
  }finally{writing=false;}
}
async function set(p,d){
  const input=document.getElementById('value'+p+'-'+d);
  if(!input)return;
  try{
    notice('Saving…');
    const response=await command('JS',JSON.stringify([{parameter:p,value:input.value.replace(/\.$/,'').replaceAll(' ','_'),type:1,destination:d}]));
    const result=await response.json();
    if(!Object.keys(result).length||Object.values(result).some(x=>x.status!==1))throw Error('The controller did not accept the setting.');
    notice('Saved. Reload this page to read it back.');
  }catch(error){notice(error.name==='TimeoutError'?'No response. Read the value before retrying.':error.message);}
}
async function setbit(p,d){
  const input=document.getElementById('value'+p+'-'+d);
  if(!input)return;
  const value=[...input.selectedOptions].reduce((n,o)=>n+Number(o.value),0);
  try{notice('Saving…');const response=await command('JS',JSON.stringify([{parameter:p,value:String(value),type:1,destination:d}]));const result=await response.json();if(!Object.keys(result).length||Object.values(result).some(x=>x.status!==1))throw Error('The controller did not accept the setting.');notice('Saved. Reload this page to read it back.');}catch(error){notice(error.message);}
}
document.addEventListener('DOMContentLoaded',()=>{
  for(const control of document.querySelectorAll('input:not([type=hidden]):not([type=submit]),select')){
    const cells=control.closest('tr')?.cells;
    if(cells&&!control.labels?.length)control.setAttribute('aria-label',[...cells].slice(0,-1).map(x=>x.textContent.trim()).join(' / '));
  }
  for(const form of document.forms){
    form.noValidate=true;
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(form.dataset.busy)return;
      form.dataset.busy='1';const submit=form.querySelector('[type=submit]');if(submit)submit.disabled=true;
      try{notice('Saving…');const body=new URLSearchParams(new FormData(form));await command(new URL(form.action).pathname.slice(new URL(root()).pathname.length),body,'application/x-www-form-urlencoded');location.href=root()+'C';}catch(error){notice(error.name==='TimeoutError'?'No response. Reload settings before retrying.':error.message);delete form.dataset.busy;if(submit)submit.disabled=false;}
    });
  }
});
