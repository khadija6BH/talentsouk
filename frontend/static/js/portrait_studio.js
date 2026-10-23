(() => {
 const form=document.getElementById('portrait-form');if(!form)return;
 const gallery=document.getElementById('portrait-gallery'),status=document.getElementById('portrait-status'),button=document.getElementById('portrait-generate');
 const source=document.getElementById('portrait-source-preview'),sourcePlaceholder=document.getElementById('portrait-source-placeholder'),result=document.getElementById('portrait-result-preview'),resultPlaceholder=document.getElementById('portrait-result-placeholder');
 let sourceUrl='',busy=false;
 const studio=document.getElementById('cv-portrait-studio');
 function studioLabel(){studio.querySelector('.portrait-toggle-text').textContent=studio.open?'Close studio':'Open studio';studio.querySelector('.portrait-toggle-icon').textContent=studio.open?'−':'↗';}
 studio.addEventListener('toggle',studioLabel);studioLabel();
 function openFromHash(){if(location.hash==='#cv-portrait-studio')studio.open=true;}
 window.addEventListener('hashchange',openFromHash);openFromHash();
 document.querySelectorAll('[data-open-portrait-studio]').forEach(link=>link.addEventListener('click',()=>{studio.open=true;studioLabel();}));
 const canvas=document.createElement('canvas');canvas.width=canvas.height=1024;
 function freePreview(){
  if(form.elements.mode.value!=='free'||!source.naturalWidth)return;
  const ctx=canvas.getContext('2d'),zoom=Number(form.elements.zoom.value),size=Math.min(source.naturalWidth,source.naturalHeight)/zoom;
  const sx=(source.naturalWidth-size)/2,sy=(source.naturalHeight-size)*Number(form.elements.framing.value)/100;
  ctx.fillStyle='#f4f1f5';ctx.fillRect(0,0,1024,1024);ctx.filter='brightness('+form.elements.brightness.value+'%) contrast(102%)';
  ctx.drawImage(source,sx,sy,size,size,16,16,992,992);ctx.filter='none';
  result.src=canvas.toDataURL('image/jpeg',0.9);result.hidden=false;resultPlaceholder.hidden=true;
 }
 function modeChanged(){
  const ai=form.elements.mode.value==='ai';document.getElementById('portrait-ai-controls').hidden=!ai;document.getElementById('portrait-free-controls').hidden=ai;
  form.elements.consent.required=ai;button.textContent=ai?'Generate AI portrait':'Enhance & save photo · Free';status.textContent='';if(!ai)freePreview();
 }
 source.addEventListener('load',freePreview);form.elements.mode.addEventListener('change',modeChanged);
 ['zoom','framing','brightness'].forEach(name=>form.elements[name].addEventListener('input',freePreview));modeChanged();
 const make=(tag,cls,text)=>{const element=document.createElement(tag);element.className=cls;if(text!==undefined)element.textContent=text;return element;};
 form.elements.photo.addEventListener('change',()=>{
  if(sourceUrl){URL.revokeObjectURL(sourceUrl);sourceUrl='';}
  const file=form.elements.photo.files[0];status.textContent='';result.hidden=true;resultPlaceholder.hidden=false;
  if(file&&(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>5*1024*1024)){form.elements.photo.value='';status.textContent='Choose a JPG, PNG or WebP image up to 5 MB.';}
  else if(file)sourceUrl=URL.createObjectURL(file);
  source.hidden=!sourceUrl;sourcePlaceholder.hidden=Boolean(sourceUrl);if(sourceUrl)source.src=sourceUrl;else source.removeAttribute('src');
 });
 function addCard(item){
  const card=make('article','portrait-gallery-card');card.dataset.portraitId=item.id;
  const img=make('img','');img.src=item.url;img.alt=item.style+' professional portrait';img.loading='lazy';
  const body=make('div','');body.append(make('h4','',item.style));const state=make('p','portrait-card-status','Ready to review');state.setAttribute('aria-live','polite');body.append(state);
  const actions=make('div','portrait-card-actions');for(const [target,label] of [['cv','Use in CV'],['profile','Use as app profile'],['both','Use for both']]){const use=make('button',target==='cv'?'btn btn-primary':'btn btn-secondary',label);use.type='button';use.dataset.portraitTarget=target;actions.append(use);}
  const download=make('a','','Download ↓');download.href=item.download_url;download.download='';actions.append(download);body.append(actions);card.append(img,body);gallery.prepend(card);document.getElementById('portrait-gallery-empty').hidden=true;
 }
 form.addEventListener('submit',async event=>{
  event.preventDefault();if(busy)return;busy=true;button.disabled=true;const ai=form.elements.mode.value==='ai';button.textContent=ai?'Generating your portrait…':'Saving your enhanced photo…';status.textContent=ai?'Creating your portrait. This can take up to two minutes. Keep this page open.':'Saving your photo without an AI provider…';
  try{
   const payload=new FormData(form);if(!ai){if(!source.complete||!source.naturalWidth)throw new Error('Wait for your photo to load first.');freePreview();const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',0.9));if(!blob)throw new Error('Could not prepare this photo. Try another image.');payload.set('photo',blob,'enhanced-photo.jpg');}const response=await fetch(form.dataset.generateUrl,{method:'POST',body:payload});if(response.redirected)throw new Error('Your session has ended. Sign in again to continue.');const data=await response.json();if(!response.ok)throw new Error(data.error||'Portrait generation failed. Please try again.');
   addCard(data.portrait);result.src=data.portrait.url;result.hidden=false;resultPlaceholder.hidden=true;status.textContent='Your portrait is ready. Review it, then choose where to use it below.';
  }catch(error){status.textContent=error instanceof SyntaxError?'The portrait service could not respond. Please try again.':error.message;}finally{busy=false;button.disabled=false;button.textContent=form.elements.mode.value==='ai'?'Generate AI portrait':'Enhance & save photo · Free';}
 });
 gallery.addEventListener('click',async event=>{
  const use=event.target.closest('[data-portrait-target]');if(!use)return;
  const card=use.closest('[data-portrait-id]'),state=card.querySelector('.portrait-card-status'),target=use.dataset.portraitTarget;
  card.querySelectorAll('button').forEach(item=>item.disabled=true);state.textContent='Saving selection…';
  try{
   const response=await fetch('/api/cv-builder/portraits/'+encodeURIComponent(card.dataset.portraitId)+'/use',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target})});if(response.redirected)throw new Error('Your session has ended. Sign in again to continue.');const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not save your portrait selection.');
   if(target==='cv'||target==='both'){
    document.dispatchEvent(new CustomEvent('cv-photo-change',{detail:{url:data.cv_photo_url}}));
    const photo=document.getElementById('cv-current-photo');photo.src=data.cv_photo_url;photo.hidden=false;document.getElementById('cv-photo-placeholder').hidden=true;
    gallery.querySelectorAll('.portrait-card-status').forEach(item=>{if(item.textContent==='Selected for your CV')item.textContent='Ready to review';});
   }
   if(target==='profile'||target==='both')document.querySelectorAll('#profile-menu-trigger img[alt="Your profile avatar"]').forEach(img=>img.src=data.profile_photo_url);
   state.textContent=target==='both'?'Selected for CV and app profile':target==='cv'?'Selected for your CV':'Selected as your app profile photo';status.textContent='Portrait selection saved.';
  }catch(error){state.textContent=error.message;}finally{card.querySelectorAll('button').forEach(item=>item.disabled=false);}
 });
 window.addEventListener('pagehide',()=>{if(sourceUrl)URL.revokeObjectURL(sourceUrl);});
})();
