(() => {
  document.querySelectorAll('[data-tool-tabs]').forEach(nav => {
    const buttons = [...nav.querySelectorAll('[data-tool-panel]')];
    const panels = buttons.map(button => document.getElementById(button.dataset.toolPanel)).filter(Boolean);
    function select(id) {
      panels.forEach(panel => panel.hidden = panel.id !== id);
      buttons.forEach(button => {const active = button.dataset.toolPanel === id; button.setAttribute('aria-selected', String(active)); button.tabIndex=active?0:-1; button.classList.toggle('is-active', active);});
    }
    function fromHash() {const target = document.getElementById(location.hash.slice(1)); const panel = panels.find(panel => panel === target || panel.contains(target)); if(panel) select(panel.id);}
    buttons.forEach(button => button.addEventListener('click', () => {select(button.dataset.toolPanel); history.replaceState(null, '', '#'+button.dataset.toolPanel);}));
    nav.addEventListener('keydown', event => {
      const index=buttons.indexOf(document.activeElement);if(index<0)return;
      let next=index;if(event.key==='ArrowRight')next=(index+1)%buttons.length;else if(event.key==='ArrowLeft')next=(index+buttons.length-1)%buttons.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=buttons.length-1;else return;
      event.preventDefault();buttons[next].click();buttons[next].focus();
    });
    select(panels[0]?.id); fromHash(); window.addEventListener('hashchange', fromHash);
  });
})();
