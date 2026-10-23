(() => {
 const source=document.getElementById('dashboard-chart-data');if(!source)return;
 const colors=['#A5BCD6','#4D0E12','#F5EFC6','#4A2E27','#231815'];
 const tr=text=>window.translateText?window.translateText(text):text;
 const el=(tag,cls,text)=>{const node=document.createElement(tag);node.className=cls||'';if(text!==undefined)node.textContent=text;return node;};
 const svgEl=(tag,attrs)=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,value));return node;};
 const percent=(value,total)=>total?Math.round(value/total*1000)/10:0;
 const shade=color=>'#'+color.slice(1).match(/../g).map(channel=>Math.round(parseInt(channel,16)*.58).toString(16).padStart(2,'0')).join('');
 const point=(r,a)=>[140+r*Math.cos(a),130+r*Math.sin(a)];
 function ring(start,end){
  const outer=point(100,start),inner=point(76,start),endOuter=point(100,end),endInner=point(76,end),large=end-start>Math.PI?1:0;
  if(end-start>=Math.PI*2-.001){const opposite=point(100,start+Math.PI),inside=point(76,start+Math.PI);return `M${outer} A100,100 0 1 1 ${opposite} A100,100 0 1 1 ${outer} L${inner} A76,76 0 1 0 ${inside} A76,76 0 1 0 ${inner} Z`;}
  return `M${outer} A100,100 0 ${large} 1 ${endOuter} L${endInner} A76,76 0 ${large} 0 ${inner} Z`;
 }
 function donut(root,rows,total,defaultLabel){
  root.replaceChildren();const stage=el('div','dc-donut-stage'),svg=svgEl('svg',{viewBox:'0 0 280 260',class:'dc-donut-svg'}),depth=svgEl('g',{transform:'translate(0 18)'}),surface=svgEl('g',{});
  svg.append(surface);const center=el('div','dc-donut-center'),number=el('strong','',total),label=el('span','',tr(defaultLabel));center.append(number,label);stage.append(svg,center);root.append(stage);
  const legend=el('div','dc-legend'),buttons=[],segments=[];let cursor=-Math.PI/2,selected=-1;
  function highlight(index){buttons.forEach((button,i)=>button.classList.toggle('is-selected',i===index));segments.forEach((segment,i)=>segment.style.opacity=index<0||index===i?'1':'.35');number.textContent=index<0?total:rows[index].count;label.textContent=index<0?tr(defaultLabel):`${tr(rows[index].label)} · ${percent(rows[index].count,total)}%`;}
  rows.forEach((row,index)=>{
   const color=colors[index%colors.length],end=cursor+(total?row.count/total*Math.PI*2:0);
   if(row.count>0){const path=ring(cursor,end),bottom=svgEl('path',{d:path,fill:shade(color)}),top=svgEl('path',{d:path,fill:color,tabindex:'0',role:'button','aria-label':`${tr(row.label)}: ${row.count} (${percent(row.count,total)}%)`,'aria-pressed':'false'});depth.append(bottom);surface.append(top);segments[index]=top;
    top.addEventListener('pointerenter',()=>highlight(index));top.addEventListener('pointerleave',()=>highlight(selected));top.addEventListener('focus',()=>highlight(index));top.addEventListener('blur',()=>highlight(selected));top.addEventListener('click',()=>choose(index));top.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose(index);}});
   } else {segments[index]=svgEl('g',{});}
   cursor=end;
   const button=el('button','dc-legend-row');button.type='button';button.setAttribute('aria-pressed','false');const dot=el('i','');dot.style.background=color;const title=el('span','',tr(row.label)),value=el('strong','',row.count);button.append(dot,title,value);button.addEventListener('click',()=>choose(index));legend.append(button);buttons.push(button);
  });
  function choose(index){selected=selected===index?-1:index;buttons.forEach((button,i)=>button.setAttribute('aria-pressed',String(i===selected)));segments.forEach((segment,i)=>segment.setAttribute('aria-pressed',String(i===selected)));highlight(selected);}
  if(!total){surface.append(svgEl('path',{d:ring(0,Math.PI*2),fill:'#F5EFC6'}));}
  const reset=el('button','dc-reset',tr('Show all'));reset.type='button';reset.addEventListener('click',()=>{selected=-1;highlight(-1);buttons.forEach(button=>button.setAttribute('aria-pressed','false'));segments.forEach(segment=>segment.setAttribute('aria-pressed','false'));});root.append(legend,reset);
 }
 function horizontal(root,rows,total){
  root.replaceChildren();const toolbar=el('label','dc-toolbar',tr('Chart view')),select=el('select','');[['count','Count'],['percent','Percentage']].forEach(([value,label])=>{const option=el('option','',tr(label));option.value=value;select.append(option);});select.value=root.dataset.mode||'count';toolbar.append(select);root.append(toolbar);const list=el('div','dc-bars'),detail=el('p','dc-detail',tr('Tap a bar to see its details.'));root.append(list,detail);
  const max=Math.max(1,...rows.map(row=>row.count));
  function draw(){list.replaceChildren();rows.forEach((row,index)=>{
   const node=el(row.url?'a':'button','dc-bar-row');if(row.url)node.href=row.url;else node.type='button';const heading=el('div','dc-bar-label'),label=el('span','',tr(row.label)),value=el('strong','',select.value==='percent'?`${percent(row.count,total)}%`:row.count);heading.append(label,value);
   const track=el('div','dc-bar-track'),bar=el('span','dc-bar');bar.style.setProperty('--dc-fill',colors[index%colors.length]);bar.style.setProperty('--dc-side',shade(colors[index%colors.length]));bar.style.setProperty('--dc-size',`${select.value==='percent'?percent(row.count,total):row.count/max*100}%`);if(!row.count)bar.hidden=true;track.append(bar);node.append(heading,track);list.append(node);
   const show=()=>detail.textContent=`${tr(row.label)}: ${row.count} · ${percent(row.count,total)}%`;
   node.addEventListener('pointerenter',show);node.addEventListener('focus',show);if(!row.url)node.addEventListener('click',show);
  });}
  select.addEventListener('change',()=>{root.dataset.mode=select.value;draw();});draw();
 }
 function daily(root,days){
  root.replaceChildren();const stage=el('div','dc-daily'),detail=el('p','dc-detail',tr('Tap a bar to see its details.'));root.append(stage,detail);const max=Math.max(1,...days.map(day=>day.count));
  days.forEach((day,index)=>{const button=el('button','dc-day');button.type='button';button.setAttribute('aria-label',`${day.date}: ${day.count}`);const number=el('strong','',day.count),track=el('div','dc-day-track'),bar=el('span','dc-day-bar'),date=el('span','dc-day-date',day.date.slice(5));bar.style.setProperty('--dc-fill',colors[index%colors.length]);bar.style.setProperty('--dc-side',shade(colors[index%colors.length]));bar.style.setProperty('--dc-height',`${day.count/max*100}%`);if(!day.count)bar.hidden=true;track.append(bar);button.append(number,track,date);stage.append(button);const show=()=>{detail.textContent=`${day.date}: ${day.count}`;stage.querySelectorAll('button').forEach(item=>item.classList.toggle('is-selected',item===button));};button.addEventListener('pointerenter',show);button.addEventListener('focus',show);button.addEventListener('click',show);});
 }
 let data=JSON.parse(source.textContent),signature='';
 const roots=[...document.querySelectorAll('[data-dashboard-chart]')];
 const observer='IntersectionObserver' in window?new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('dc-ready');observer.unobserve(entry.target);}}),{threshold:.12}):null;
 function render(){
  const summary=document.getElementById("dc-recent-summary");if(summary)summary.textContent=tr(`${data.activity.recent} saved records · dates in UTC. Includes records created and interview practices completed.`);
  roots.forEach(root=>{const kind=root.dataset.dashboardChart,company=data.company,activity=data.activity;
   if(kind==='categories')donut(root,company.category_chart.map(row=>({label:row.name,count:row.count})),company.total,'Companies');
   if(kind==='contacts')donut(root,[{label:'With email',count:company.with_email},{label:'Without email',count:company.total-company.with_email}],company.total,'Companies');
   if(kind==='category-bars')horizontal(root,company.categories.map(([label,count])=>({label,count})),company.total);
   if(kind==='activity')horizontal(root,activity.groups,activity.total);
   if(kind==='days')daily(root,activity.days);
   if(observer)observer.observe(root);else root.classList.add('dc-ready');
  });
 }
 render();document.addEventListener('app:languagechange',render);
 // Refresh only changed count data. Do not interrupt keyboard or touch interaction.
 let loading=false;
 async function refresh(){if(document.hidden||loading||document.activeElement?.closest('.dashboard-chart'))return;loading=true;try{const response=await fetch('/api/dashboard/charts',{cache:'no-store'});if(!response.ok)return;const next=await response.json(),key=JSON.stringify(next);if(key!==signature){signature=key;data=next;render();}}catch(_){/* Keep the last successful chart data. */}finally{loading=false;}}
 signature=JSON.stringify(data);setInterval(refresh,60000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
})();
