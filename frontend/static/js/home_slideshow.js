(() => {
  const carousel = document.querySelector('.career-slideshow');
  if (!carousel) return;
  const slides = [...carousel.querySelectorAll('.career-slide')];
  if (slides.length < 2) return;
  let index = 0, timer = null;
  function show(next) {
    index = next % slides.length;
    slides.forEach((slide, i) => {
      slide.classList.toggle('is-active', i === index);
      slide.setAttribute('aria-hidden', String(i !== index));
    });
  }
  function run() {
    clearInterval(timer);
    timer = document.hidden ? null : setInterval(() => show(index + 1), 5000);
  }
  document.addEventListener('visibilitychange', run);
  window.addEventListener('pagehide', () => clearInterval(timer));
  window.addEventListener('pageshow', run);
  carousel.querySelectorAll('img').forEach(img => img.addEventListener('error', () => {
    img.hidden = true;
    img.closest('figure').style.background = 'linear-gradient(135deg,#673147,#311432)';
  }));
  run();
})();
