(() => {
  const workspace=document.getElementById('radar-workspace');
  if(!workspace)return;
  const search=document.getElementById('radar-search'),form=document.getElementById('radar-refresh');
  const source=document.getElementById('import-source'),country=document.getElementById('import-country');
  let dirty=false,busy=false,completed=workspace.dataset.completed;
  workspace.querySelectorAll('form').forEach(item=>{
    item.addEventListener('input',()=>dirty=true);
    item.addEventListener('change',()=>dirty=true);
  });
  function setBusy(item,label){
    if(busy)return;busy=true;item.classList.add('radar-busy');item.setAttribute('aria-busy','true');
    const button=item.querySelector('button[type=submit]');button.disabled=true;
    button.querySelector('.radar-button-label').textContent=label;
  }
  search.addEventListener('submit',()=>setBusy(search,'Finding offers…'));
  form.addEventListener('submit',()=>setBusy(form,'Refreshing offers…'));
  window.addEventListener('pageshow',()=>{
    busy=false;
    for(const [item,label] of [[search,'Find offers'],[form,'Refresh offers']]){
      item.classList.remove('radar-busy');item.removeAttribute('aria-busy');
      const button=item.querySelector('button[type=submit]');button.disabled=false;
      button.querySelector('.radar-button-label').textContent=label;
    }
  });
  const notes={jobicy:'Latest remote offers (up to 100). Check each offer’s location restrictions. Responses are cached for one hour.',local_csv:'The local file is read without contacting job websites.',jooble:'Search up to five pages of Jooble Morocco results. Your key stays on the server.',adzuna:'Import up to five pages of search results. Your credentials stay on the server.',arbeitnow:'Search within the latest Germany feed (up to 100 offers). Remote offers can have location restrictions.'};
  function selectSource(){
    const supported={jooble:['ma'],adzuna:['fr','gb','de','us'],arbeitnow:['de'],jobicy:['remote']}[source.value];
    [...country.options].forEach(option=>option.disabled=Boolean(supported&&!supported.includes(option.value)));
    country.disabled=source.value==='local_csv';
    if(supported&&!supported.includes(country.value))country.value=supported[0];
    form.querySelectorAll('input').forEach(input=>input.disabled=source.value==='local_csv');
    document.getElementById('source-help').textContent=notes[source.value];
  }
  source.addEventListener('change',selectSource);selectSource();
  document.querySelector('#radar-new-offers button').addEventListener('click',()=>search.requestSubmit());
  setInterval(async()=>{
    if(document.hidden||busy)return;
    try{
      const response=await fetch('/api/opportunities/status');if(!response.ok)return;
      const data=await response.json();
      if(data.completed&&data.completed!==completed){
        if(dirty||document.querySelector('.radar-import[open]')||['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName))document.getElementById('radar-new-offers').classList.remove('hidden');
        else location.reload();
      }
    }catch(_){/* Saved results remain available. */}
  },60000);
})();
