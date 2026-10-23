(() => {
 const guide=document.getElementById('tutorial-guide');if(!guide)return;
 const spotlight=document.getElementById('tutorial-highlight'),error=document.getElementById('tutorial-error');
 let step=JSON.parse(guide.dataset.step),target=null,busy=false;
 function position(){
  if(!target||!target.isConnected){spotlight.hidden=true;return;}
  const box=target.getBoundingClientRect();
  spotlight.hidden=box.width===0||box.height===0;
  Object.assign(spotlight.style,{left:Math.max(4,box.left-6)+'px',top:box.top-6+'px',width:Math.min(innerWidth-8,box.width+12)+'px',height:box.height+12+'px'});
 }
 function render(){
  document.getElementById('tutorial-progress').textContent='STEP '+(step.index+1)+' OF '+step.total+' · '+step.label;
  document.getElementById('tutorial-title').textContent=step.title;document.getElementById('tutorial-description').textContent=step.text;
  document.getElementById('tutorial-progress-bar').value=step.index+1;
  document.getElementById('tutorial-back').hidden=step.index===0;
  const next=document.getElementById('tutorial-next');next.textContent=step.index===step.total-1?'Finish tutorial ✓':'Next →';next.dataset.tutorialAction=step.index===step.total-1?'finish':'next';
  target=document.querySelector(step.selector);
  if(target){if(step.selector.startsWith('#cv-portrait-studio'))target.closest('details').open=true;target.scrollIntoView({block:'center',behavior:'instant'});}
  position();next.focus({preventScroll:true});
 }
 guide.addEventListener('click',async event=>{
  const button=event.target.closest('[data-tutorial-action]');if(!button||busy)return;
  busy=true;error.hidden=true;guide.querySelectorAll('button').forEach(item=>item.disabled=true);
  try{
   const response=await fetch(guide.dataset.actionUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:button.dataset.tutorialAction})});
   if(response.redirected)throw new Error('Please sign in again to continue.');
   const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not save your tutorial progress.');
   const url=new URL(data.url,location.origin);
   if(data.step&&url.pathname===location.pathname&&url.search===location.search){step=data.step;render();}
   else location.assign(url.href);
  }catch(problem){error.textContent=problem instanceof SyntaxError?'Could not save your tutorial progress. Please try again.':problem.message;error.hidden=false;}
  finally{busy=false;guide.querySelectorAll('button').forEach(item=>item.disabled=false);if(error.hidden)document.getElementById('tutorial-next').focus({preventScroll:true});else button.focus({preventScroll:true});}
 });
 addEventListener('resize',position);addEventListener('scroll',position,{passive:true});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();guide.querySelector('[data-tutorial-action="skip"]').click();}});
 render();
})();
