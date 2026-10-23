(() => {
  const nav = document.querySelector('.settings-side-nav');
  if (!nav) return;
  const links = [...nav.querySelectorAll('[data-settings-target]')];
  const panels = [...document.querySelectorAll('[data-settings-panel]')];
  const save = document.querySelector('[data-settings-save]');
  function activate() {
    const hash = location.hash.replace('#settings-', '');
    const key = location.hash === '#notifications' ? 'notifications' : links.some(link => link.dataset.settingsTarget === hash) ? hash : 'general';
    for (const panel of panels) panel.hidden = panel.dataset.settingsPanel !== key;
    for (const link of links) {
      const active = link.dataset.settingsTarget === key;
      link.classList.toggle('is-active', active);
      if (active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    }
    if (save) save.hidden = !['general', 'notifications', 'privacy', 'ai'].includes(key);
    for (const form of document.querySelectorAll('.settings-shell form')) {
      if (form.action.includes('/settings/preferences') || form.querySelector('#settings-language')) {
        const target = new URL(form.action);
        target.hash = 'settings-' + key;
        form.action = target.toString();
      }
    }
  }
  window.addEventListener('hashchange', activate);
  activate();
})();
