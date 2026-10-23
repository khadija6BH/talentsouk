(() => {
 const form=document.getElementById('skills-quiz');if(!form)return;
 const questions=[...form.querySelectorAll('.skill-question')];let current=0;
 const previous=document.getElementById('skills-previous'),next=document.getElementById('skills-next'),save=document.getElementById('skills-save');
 function show(){questions.forEach((q,i)=>q.hidden=i!==current);previous.disabled=current===0;next.hidden=current===questions.length-1;save.hidden=current!==questions.length-1;document.getElementById('skills-question-count').textContent=`Question ${current+1} of ${questions.length}`;document.getElementById('skills-progress-fill').style.width=((current+1)/questions.length*100)+'%';}
 function feedback(q,errorOnly=false){const selected=q.querySelector('input:checked'),box=q.querySelector('.skill-live-feedback');if(errorOnly&&selected)return true;box.hidden=false;if(!selected){box.className='skill-live-feedback is-incorrect';box.querySelector('strong').textContent='Select an answer first.';box.querySelector('p').textContent='';return false;}if(errorOnly)return true;const correct=selected.value===q.dataset.correct;box.className='skill-live-feedback '+(correct?'is-correct':'is-incorrect');box.querySelector('strong').textContent=correct?'Correct answer!':'Incorrect answer — keep practicing.';box.querySelector('p').textContent=q.querySelector('.skill-explanation-source').textContent;return true;}
 questions.forEach(q=>{q.querySelector('.skill-check').hidden=false;q.querySelector('.skill-check').addEventListener('click',()=>feedback(q));q.addEventListener('change',()=>q.querySelector('.skill-live-feedback').hidden=true);});
 previous.addEventListener('click',()=>{if(current>0){current--;show();}});next.addEventListener('click',()=>{if(feedback(questions[current],true)){current++;show();}});
 form.querySelector('.skills-navigation').hidden=false;show();
 form.addEventListener('submit',event=>{const missing=questions.findIndex(q=>!q.querySelector('input:checked'));if(missing>=0){event.preventDefault();current=missing;show();feedback(questions[current],true);return;}save.disabled=true;save.textContent='Saving…';form.setAttribute('aria-busy','true');});
})();
