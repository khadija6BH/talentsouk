(() => {
 const button=document.getElementById('generate-bio');
 if(!button)return;
 const bio=document.getElementById('portfolio-bio');
 const status=document.getElementById('bio-status');
 button.addEventListener('click',async()=>{
  const original=bio.value;
  button.disabled=true;button.textContent='Generating…';status.textContent='';
  bio.setAttribute('aria-busy','true');
  try{
   const response=await fetch(button.dataset.url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({headline:document.querySelector('[name="headline"]').value,language:document.getElementById('bio-language').value})});
   const data=await response.json();
   if(!response.ok)throw new Error(data.error||'Generation failed. Please try again.');
   if(typeof data.bio!=='string'||!data.bio.trim())throw new Error('No introduction was returned. Please try again.');
   if(bio.value!==original){status.textContent='Your text changed during generation. Kept your edits; try again when ready.';return;}
   bio.value=data.bio;bio.dispatchEvent(new Event('input',{bubbles:true}));
   status.textContent='Generated. Review your text, then save changes.';bio.focus();
  }catch(error){status.textContent=error.message;}
  finally{button.disabled=false;button.textContent='✧ Generate with AI';bio.removeAttribute('aria-busy');}
 });
})();
