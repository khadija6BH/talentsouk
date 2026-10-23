(() => {
 const table=document.getElementById('applications-table');
 const board=document.getElementById('application-board');
 if(!board)return;
 if(!table){board.hidden=true;document.querySelector('.view-switch')?.setAttribute('hidden','');return;}
 const rows=[...table.tBodies[0].rows];
 const statuses=JSON.parse(board.dataset.statuses);
 const make=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(text!==undefined)el.textContent=text;return el;};
 function render(){
  board.replaceChildren();
  const visible=rows.filter(row=>!row.hidden);
  const query=document.getElementById('application-search').value.trim();
  const filter=document.getElementById('application-status-filter').value;
  for(const status of statuses.filter(s=>filter==='all'||filter===s)){
   const lane=make('section','pipeline-lane');lane.setAttribute('aria-label',status+' applications');
   const selected=visible.filter(row=>row.dataset.status===status);
   if(query && !selected.length)continue;
   const head=make('div','pipeline-lane-head');head.append(make('h2','',status),make('span','',String(selected.length)));lane.append(head);
   for(const row of selected){
    const card=make('article','pipeline-card');
    const company=row.querySelector('.application-company');
    card.append(make('div','pipeline-avatar',company.textContent.trim().split(/\s+/).slice(0,2).map(w=>w[0]).join('').toUpperCase()));
    card.append(make('h3','',row.querySelector('[data-label="Position"] strong').textContent));
    const link=make('a','company',company.textContent);link.href=company.href;card.append(link);
    const date=make('time','',row.dataset.applied.slice(0,10)||'Date not recorded');card.append(date);
    const select=row.querySelector('.tracking-status').cloneNode(true);
    select.addEventListener('change',()=>{const source=row.querySelector('.tracking-status');source.value=select.value;source.dispatchEvent(new Event('change'));select.disabled=true;});
    card.append(select);
    const next=make('div','pipeline-next');next.append(make('small','','Next step'));
    const due=row.querySelector('[data-label="AI match"] p');
    const hints={Wishlist:'Review this opportunity',Draft:'Prepare your application',Sent:'Plan a follow-up',Replied:'Reply to the recruiter',Interview:'Prepare for your interview',Accepted:'Review the offer',Rejected:'Explore another opportunity'};
    next.append(make('p','',due?.textContent||hints[status]));card.append(next);
    const follow=row.querySelector('.add-reminder');if(follow){const button=make('button','mt-3 text-xs underline','+ Follow-up');button.type='button';button.addEventListener('click',()=>follow.click());card.append(button);}
    for(const detail of row.querySelectorAll('details'))card.append(detail.cloneNode(true));
    const version=row.querySelector('a[href*="/cv-versions/"]');if(version)card.append(version.cloneNode(true));
    const send=row.querySelector('.send-gmail');if(send){const btn=make('button','btn btn-secondary mt-3 text-xs','Send with Gmail');btn.type='button';btn.addEventListener('click',()=>send.click());card.append(btn);}
    lane.append(card);
   }
   const add=make('a','pipeline-add','＋ Add application');add.href=board.dataset.addUrl;lane.append(add);board.append(lane);
  }
 }
 const observer=new MutationObserver(render);observer.observe(table.tBodies[0],{childList:true,attributes:true,subtree:true,attributeFilter:['hidden']});
 render();
 const tableWrap=table.closest('.application-table-wrap');
 function view(mode){board.hidden=mode!=='board';tableWrap.hidden=mode!=='list';document.querySelectorAll('[data-application-view]').forEach(btn=>btn.setAttribute('aria-pressed',String(btn.dataset.applicationView===mode)));}
 document.querySelectorAll('[data-application-view]').forEach(btn=>btn.addEventListener('click',()=>view(btn.dataset.applicationView)));
 view('board');
})();
