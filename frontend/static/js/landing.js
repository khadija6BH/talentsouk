(() => {
  const finishIntro = () => {
    document.documentElement.classList.remove('show-brand-intro');
    try { sessionStorage.setItem('talentsouk-intro', '1'); } catch (_) {}
  };
  if (document.documentElement.classList.contains('show-brand-intro')) {
    window.setTimeout(finishIntro, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 100 : 2200);
  }

  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add('visible'); observer.unobserve(entry.target); }
    }), { threshold: 0.08 });
    document.querySelectorAll('.reveal').forEach(section => observer.observe(section));
    document.documentElement.classList.add('motion-ready');
  }
})();
