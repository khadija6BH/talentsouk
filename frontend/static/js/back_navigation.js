(() => {
  const buttons=[...document.querySelectorAll('[data-app-back]')];
  // Remember whether this history entry followed another TalentSouk page.
  // A new tab's blank entry is not an application page.
  const current=window.history.state;
  const state=current && typeof current==='object' ? current : {};
  if(typeof state.talentsoukCanGoBack!=='boolean'){
    let internal=false;
    try{internal=Boolean(document.referrer)&&new URL(document.referrer).origin===window.location.origin;}catch(_){ }
    try{window.history.replaceState({...state,talentsoukCanGoBack:internal&&window.history.length>1},'');}catch(_){ }
  }
  function canGoBack(){return window.history.length>1&&window.history.state?.talentsoukCanGoBack===true;}
  function update(){buttons.forEach(button=>button.closest('[data-back-container]').hidden=!canGoBack());}
  buttons.forEach(button=>button.addEventListener('click',()=>{if(canGoBack())window.history.back();}));
  update();window.addEventListener('pageshow',update);window.addEventListener('popstate',update);
})();
