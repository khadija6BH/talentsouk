(() => {
  const root=document.documentElement;
  const media=window.matchMedia('(prefers-color-scheme: dark)');
  const saved={theme:root.dataset.theme||'plum',mode:root.dataset.mode||'light'};
  function apply(theme,mode){root.dataset.theme=theme;root.dataset.mode=mode;root.dataset.colorMode=mode==='system'?(media.matches?'dark':'light'):mode;}
  apply(saved.theme,saved.mode);
  media.addEventListener('change',()=>apply(root.dataset.theme,root.dataset.mode));
  document.addEventListener('DOMContentLoaded',()=>{
    document.querySelectorAll('[data-appearance-picker]').forEach(form=>{
      let photoUrl='';const photo=form.querySelector('[name="profile_photo"]'),preview=form.querySelector('[data-avatar-preview]'),error=form.querySelector('[data-appearance-error]');
      const originalAvatar=preview.src;
      function update(){
        const theme=form.querySelector('[name="theme"]:checked')?.value||saved.theme;
        const mode=form.querySelector('[name="mode"]:checked')?.value||saved.mode;
        apply(theme,mode);
        const avatar=form.querySelector('[name="avatar"]:checked');
        preview.src=photoUrl||avatar?.dataset.avatarUrl||originalAvatar;
      }
      photo.addEventListener('change',()=>{
        if(photoUrl){URL.revokeObjectURL(photoUrl);photoUrl='';}
        const file=photo.files[0];
        const invalid=file&&(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>2*1024*1024);
        error.hidden=!invalid;error.textContent=invalid?'Choose a JPG, PNG or WebP image up to 2 MB.':'';
        if(invalid)photo.value='';else if(file){photoUrl=URL.createObjectURL(file);form.querySelectorAll('[name="avatar"]').forEach(input=>{input.checked=false;});}
        update();
      });
      form.querySelectorAll('[name="theme"],[name="mode"],[name="avatar"]').forEach(input=>input.addEventListener('change',()=>{
        if(input.name==='avatar'&&photoUrl){URL.revokeObjectURL(photoUrl);photoUrl='';photo.value='';}
        update();
      }));
      form.addEventListener('reset',()=>{
        if(photoUrl){URL.revokeObjectURL(photoUrl);photoUrl='';}error.hidden=true;
        requestAnimationFrame(()=>{apply(saved.theme,saved.mode);preview.src=originalAvatar;});
      });
      form.addEventListener('submit',()=>{const button=form.querySelector('[type="submit"]');button.disabled=true;button.textContent='Saving…';});
      window.addEventListener('pagehide',()=>{if(photoUrl)URL.revokeObjectURL(photoUrl);});
    });
  });
})();
