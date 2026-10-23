(() => {
 const side = document.getElementById('sidebar');
 const wide = matchMedia('(min-width:1200px)');
 function sync() {
  side.inert = !wide.matches;
  side.setAttribute('aria-hidden', String(!wide.matches));
  if (wide.matches) { side.removeAttribute('role'); side.removeAttribute('aria-modal'); }
  else { side.setAttribute('role', 'dialog'); side.setAttribute('aria-modal', 'true'); }
 }
 wide.addEventListener('change', sync);
 sync();
})();
