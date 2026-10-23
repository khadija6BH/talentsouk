(() => {
 const panel = document.getElementById('job-preview-panel');
 const cards = [...document.querySelectorAll('[data-offer-card]')];
 if (!panel || !cards.length) { if (panel) panel.hidden = true; return; }
 function select(card, focus) {
   cards.forEach(item => {
     item.classList.toggle('selected-offer', item === card);
     item.querySelector('.offer-preview-button').setAttribute('aria-pressed', String(item === card));
   });
   const preview = card.cloneNode(true);
   preview.removeAttribute('data-offer-card');
   preview.classList.remove('selected-offer');
   preview.querySelector('.offer-preview-button').remove();
   preview.querySelectorAll('details').forEach(detail => { detail.open = true; });
   panel.replaceChildren(preview);
   if (focus) {
     panel.setAttribute('tabindex','-1');
     panel.focus({preventScroll:true});
     if (matchMedia('(max-width:900px)').matches) panel.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth',block:'start'});
   }
 }
 cards.forEach(card => card.querySelector('.offer-preview-button').addEventListener('click',()=>select(card,true)));
 select(cards[0],false);
})();
