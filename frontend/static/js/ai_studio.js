(() => {
 const workspace=document.getElementById('studio-workspace');if(!workspace)return;
 const action=workspace.dataset.action,form=document.getElementById('studio-form'),result=document.getElementById('studio-result'),status=document.getElementById('studio-status'),button=document.getElementById('studio-run');
 const company=document.getElementById('studio-company'),offer=document.getElementById('studio-offer');
 const make=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(text!==undefined)el.textContent=text;return el;};
 const source=document.getElementById('studio-source'),params=new URLSearchParams(location.search);
 if([...source.options].some(o=>o.value===params.get('cv_source')))source.value=params.get('cv_source');
 function filterOffers(){if(!company||!offer)return;for(const option of offer.options)option.hidden=Boolean(option.value&&option.dataset.company!==company.value);if(offer.selectedOptions[0]?.hidden)offer.value='';}
 if(company){if(!company.value&&offer.value)company.value=offer.selectedOptions[0].dataset.company;company.addEventListener('change',filterOffers);filterOffers();}
 const category=document.getElementById('studio-category'),search=document.getElementById('studio-company-search');
 if(company&&category&&search){
  const entries=[...company.options].filter(o=>o.value).map(o=>({value:o.value,name:o.textContent,category:o.dataset.category,domains:JSON.parse(o.dataset.domains||'[]'),tech:o.dataset.tech==='true'}));
  const selected=entries.find(entry=>entry.value===company.value);if(selected)category.value=selected.category;
  function filterCompanies(){
   const previous=company.value,query=search.value.trim().toLocaleLowerCase();
   const visible=entries.filter(entry=>(!category.value||(category.value==='__tech__'?entry.tech:(entry.category===category.value||entry.domains.includes(category.value))))&&entry.name.toLocaleLowerCase().includes(query));
   company.replaceChildren(new Option(visible.length?'Choose a company':'No matching companies',''));
   const groups=new Map();for(const entry of visible){if(!groups.has(entry.category)){const group=document.createElement('optgroup');group.label=entry.category;groups.set(entry.category,group);company.append(group);}const option=new Option(entry.name,entry.value);option.dataset.category=entry.category;option.dataset.domains=JSON.stringify(entry.domains);option.dataset.tech=String(entry.tech);groups.get(entry.category).append(option);}
   company.value=visible.some(entry=>entry.value===previous)?previous:'';
   document.getElementById('studio-company-count').textContent=visible.length?visible.length+' companies available'+(category.value?' in this category':' across all categories')+'.':'No companies found. Try another name or category.';
   filterOffers();
  }
  category.addEventListener('change',filterCompanies);search.addEventListener('input',filterCompanies);filterCompanies();
 }
 let lastResult=null;
 function exportResult(){if(!lastResult)return;const blob=new Blob([JSON.stringify(lastResult,null,2)],{type:'application/json;charset=utf-8'});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='talentsouk-'+action+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);}
 document.getElementById('studio-export').addEventListener('click',exportResult);
 form.addEventListener('submit',async event=>{
  event.preventDefault();button.disabled=true;const old=button.textContent;button.textContent='Working…';status.textContent='';
  try{
   const response=await fetch(workspace.dataset.url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,source:source.value,company_id:company?.value,offer_id:offer?.value,position:document.getElementById('studio-position')?.value,language:document.getElementById('studio-language')?.value||'en'})});
   const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not complete the analysis.');
   lastResult=data;result.replaceChildren();result.className='';document.getElementById('studio-insights').hidden=true;
   if(data.match){
    const match=data.match;const score=Math.max(0,Math.min(100,Number(match.score)||0));result.append(make('h2','',score>=70?'Strong alignment':score>=40?'Some alignment':'Room to strengthen your match'));
    const ring=make('div','ai-ring');ring.style.setProperty('--score',String(score));const inner=make('div','ai-ring-inner');const number=make('span','',String(score));number.append(make('small','','/100'));inner.append(number);ring.append(inner);result.append(ring,make('p','',match.explanation));
    const factors=make('div','ai-factors');for(const [key,value] of Object.entries(match.factor_scores||{})){const block=make('div','');const label=make('label','',key.replaceAll('_',' '));label.append(make('span','',Math.round(value)+'%'));const progress=make('progress','');progress.max=100;progress.value=value;progress.setAttribute('aria-label',key);block.append(label,progress);factors.append(block);}result.append(factors);
    for(const [id,items] of [['studio-strengths',match.strong_matches],['studio-gaps',match.missing_skills]]){const list=document.getElementById(id);list.replaceChildren();for(const text of items?.length?items:['No evidence identified.'])list.append(make('li','',text));}
    document.getElementById('studio-insights').hidden=false;
   }else if(data.optimization){
    const o=data.optimization;result.append(make('h2','','Your tailored CV is ready'),make('p','',o.suggested_summary||'Your existing CV evidence has been reordered for this target.'));
    for(const text of o.suggestions||[])result.append(make('p','mt-3',text));
    const link=make('a','btn btn-primary mt-5','View saved CV version ↗');link.href='/cv-versions/'+o.version_id;link.target='_blank';link.rel='noopener';result.append(link);
    result.append(make('p','ai-note','Original CV preserved. Review the saved version before exporting.'));
   }else if(data.cover_letter){
    result.append(make('h2','','Your cover letter'));const text=make('textarea','');text.value=data.cover_letter;text.maxLength=15000;text.setAttribute('aria-label','Editable cover letter');result.append(text);
    const copy=make('button','btn btn-secondary mt-4','Copy letter');copy.type='button';copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(text.value);status.textContent='Copied. Paste the letter into your application.';}catch{ text.focus();text.select();status.textContent='Text selected. Press Ctrl+C to copy.';}});result.append(copy);
    const use=make('a','btn btn-secondary mt-4','Use in application ↗');use.href='/postulations?company_id='+encodeURIComponent(company.value)+'&offer_id='+encodeURIComponent(offer.value);use.addEventListener('click',()=>{try{sessionStorage.setItem('studio-cover-draft',JSON.stringify({text:text.value,company_id:company.value}));}catch{}});result.append(use);
   }else if(data.recommendations){
    result.append(make('h2','','Job offers for your CV'),make('p','ai-note','Ranked by overlap with your chosen CV. Scores describe alignment, not hiring probability.'));
    for(const item of data.job_recommendations||[]){
     const card=make('article','ai-recommendation ai-job-card');card.append(make('h3','',item.title),make('p','',item.company_name));
     card.append(make('p','ai-job-meta',[item.location,item.contract_type].filter(Boolean).join(' · ')),make('span','ai-match-badge',item.score+'% alignment'));
     card.append(make('p','','Matched in your CV: '+item.matched_terms.join(', ')));
     if(item.missing_skills?.length)card.append(make('p','ai-note','Skills to strengthen: '+item.missing_skills.join(', ')));
     const details=make('a','btn btn-secondary','View job offer ↗');details.href='/opportunities/'+encodeURIComponent(item.id);card.append(details);
     const analyze=make('a','ai-job-analyze','Analyze this match →');const target=new URLSearchParams({tab:'match',company_id:item.company_id,offer_id:item.id,cv_source:source.value});analyze.href='/ai-studio?'+target;card.append(analyze);result.append(card);
    }
    if(!data.job_recommendations?.length)result.append(make('p','ai-note',data.available_offer_count?'No active offers have explicit skills or keyword overlap with this CV. Try another CV or explore all offers.':'No active job offers are available right now. Check Job offers for updates.'));
    const browse=make('a','ai-discover-link','Browse all job offers →');browse.href='/jobs';result.append(browse,make('h2','mt-5','Companies for your profile'));for(const item of data.recommendations){const card=make('article','ai-recommendation');card.append(make('h3','',item.name+' · '+item.score+'%'),make('p','',item.category));const link=make('a','','View company ↗');link.href='/companies/'+item.id;card.append(link);result.append(card);}if(!data.recommendations.length)result.append(make('p','','No companies available yet.'));}
  }catch(error){status.textContent=error.message;}finally{button.disabled=false;button.textContent=old;}
 });
})();
