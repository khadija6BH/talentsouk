(() => {
const source = document.getElementById('performance-chart-data');
if (!source) return;
const data = JSON.parse(source.textContent), select = document.getElementById('performance-view'), chart = document.getElementById('performance-bars'), empty = document.getElementById('performance-chart-empty');
const palette=['#A5BCD6','#4D0E12','#F5EFC6','#4A2E27','#231815'];
const shade=color=>'#'+color.slice(1).match(/../g).map(channel=>Math.round(parseInt(channel,16)*.58).toString(16).padStart(2,'0')).join('');
function draw() {
 const hint="Select a column to explore its count.";document.getElementById("performance-chart-detail").textContent=window.translateText?window.translateText(hint):hint;
 const rows = select.value === 'months' ? data.months.map(row => ({label:row.label,count:row.sent})) : data.states;
 chart.replaceChildren(); empty.hidden = rows.length > 0; chart.hidden = !rows.length;
 const max = Math.max(1,...rows.map(row=>row.count));
 rows.forEach((row,index) => {
 const col=document.createElement('div'); col.className='performance-column'; col.tabIndex=0;col.setAttribute('role','button');col.setAttribute('aria-label',`${row.label}: ${row.count}`);col.style.setProperty('--perf-fill',palette[index%palette.length]);col.style.setProperty('--perf-side',shade(palette[index%palette.length]));const show=()=>{document.getElementById('performance-chart-detail').textContent=`${window.translateText?window.translateText(row.label):row.label}: ${row.count}`;};col.addEventListener('click',show);col.addEventListener('focus',show);col.addEventListener('pointerenter',show);col.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();show();}});
 const value=document.createElement('strong'); value.textContent=row.count;
 const track=document.createElement('div'); track.className='performance-track';track.setAttribute('aria-hidden','true');
 const bar=document.createElement('div');bar.className='performance-bar';bar.hidden=row.count===0;bar.style.setProperty('--height','0%');track.append(bar);
 const label=document.createElement('span');label.textContent=row.label;
 col.append(value,track,label);chart.append(col);
 requestAnimationFrame(()=>requestAnimationFrame(()=>bar.style.setProperty('--height',`${row.count/max*100}%`)));
 });
}
select.addEventListener('change',draw); draw();
})();
