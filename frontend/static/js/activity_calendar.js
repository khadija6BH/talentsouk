(() => {
 const source=document.getElementById('activity-calendar-data');if(!source)return;
 const data=JSON.parse(source.textContent),year=document.getElementById('activity-year'),grid=document.getElementById('activity-grid'),months=document.getElementById('activity-months'),detail=document.getElementById('activity-day-detail');
 const tr=t=>window.translateText?window.translateText(t):t;
 function draw(){
  grid.replaceChildren();months.replaceChildren();
  const y=Number(year.value),first=new Date(Date.UTC(y,0,1)),last=new Date(Date.UTC(y,11,31)),offset=(first.getUTCDay()+6)%7;
  const length=Math.round((last-first)/86400000)+1,weeks=Math.ceil((offset+length)/7),locale=document.documentElement.lang||'en';
  grid.style.setProperty('--weeks',weeks);months.style.setProperty('--weeks',weeks);
  let total=0,active=0;
  for(let m=0;m<12;m++){const date=new Date(Date.UTC(y,m,1)),label=document.createElement('span');label.textContent=new Intl.DateTimeFormat(locale,{month:'short',timeZone:'UTC'}).format(date);label.style.gridColumn=1+Math.floor((offset+Math.round((date-first)/86400000))/7);months.append(label);}
  for(let n=0;n<weeks*7;n++){
   const date=new Date(first.getTime()+(n-offset)*86400000),key=date.toISOString().slice(0,10),count=data.counts[key]||0,valid=date.getUTCFullYear()===y&&key<=data.today;
   const cell=document.createElement(valid?'button':'span');cell.className='activity-cell';
   if(valid){total+=count;if(count)active++;cell.type='button';cell.dataset.level=count===0?0:count===1?1:count<=3?2:count<=6?3:4;const text=new Intl.DateTimeFormat(locale,{dateStyle:'long',timeZone:'UTC'}).format(date)+' · '+count+' '+tr('Saved actions');cell.title=text;cell.setAttribute('aria-label',text);const show=()=>{detail.textContent=text;};cell.addEventListener('focus',show);cell.addEventListener('pointerenter',show);cell.addEventListener('click',show);}
   else {cell.classList.add('calendar-outside');cell.setAttribute('aria-hidden','true');}
   grid.append(cell);
  }
  document.getElementById('activity-total').textContent=total;document.getElementById('activity-days').textContent=active;detail.textContent=tr('Select a day to see its activity.');
 }
 year.addEventListener('change',draw);document.addEventListener('app:languagechange',draw);draw();
})();
