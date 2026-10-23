(() => {
  const form = document.getElementById('setup-form');
  const steps = [...form.querySelectorAll('.setup-step')];
  const next = document.getElementById('next');
  const back = document.getElementById('back');
  const skip = document.getElementById('skip-cv');
  const file = document.getElementById('cv-file');
  let current = 0;
  function validStep() {
    for (const input of steps[current].querySelectorAll('input')) {
      if (!input.checkValidity()) { input.reportValidity(); return false; }
    }
    return true;
  }
  function review() {
    const data = new FormData(form);
    const selectedLabel = name => {
      const input = form.querySelector(`input[name="${name}"]:checked`);
      return input ? input.closest('label').querySelector('strong,span:last-child').textContent : 'Not specified';
    };
    const rows = [
      ['Career goal', selectedLabel('career_goal'), 1], ['Target role', data.get('target_position'), 1],
      ['Skills', [...new Set([...data.getAll('target_skills_selected'), ...String(data.get('target_skills') || '').split(',').map(s => s.trim()).filter(Boolean)])].join(' · '), 2],
      ['Experience', selectedLabel('experience_level'), 3], ['Education', selectedLabel('education_level'), 4],
      ['Location', data.get('target_location'), 5], ['CV', file.files[0]?.name || 'Not added', 6]
    ];
    const container = document.getElementById('review'); container.replaceChildren();
    rows.forEach(([label, value, step]) => {
      const row = document.createElement('div'); row.className = 'review-row';
      const title = document.createElement('strong'); title.textContent = label;
      const answer = document.createElement('span'); answer.textContent = value || 'Not specified';
      const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = '✎ Edit'; edit.setAttribute('aria-label', `Edit ${label}`); edit.addEventListener('click', () => show(step));
      row.append(title, answer, edit); container.append(row);
    });
  }
  function show(index, focus = true) {
    current = index; steps.forEach((step, i) => { step.hidden = i !== current; });
    back.hidden = current === 0; document.getElementById('sign-out').hidden = current !== 0; skip.hidden = current !== 6;
    next.textContent = current === 0 ? 'Let’s get started →' : current === steps.length - 1 ? 'Complete my profile ✓' : 'Continue →';
    document.getElementById('step-label').textContent = `Step ${current + 1} of ${steps.length}`;
    document.getElementById('step-percent').textContent = `${Math.round((current + 1) / steps.length * 100)}%`;
    document.getElementById('progress-fill').style.width = `${(current + 1) / steps.length * 100}%`;
    document.querySelector('[role="progressbar"]').setAttribute('aria-valuenow', current + 1);
    if (current === steps.length - 1) review();
    if (focus) { steps[current].querySelector('h1').focus(); window.scrollTo({top: 0, behavior: 'instant'}); }
  }
  next.addEventListener('click', () => {
    if (!validStep()) return;
    if (current < steps.length - 1) show(current + 1); else form.requestSubmit();
  });
  back.addEventListener('click', () => show(current - 1));
  skip.addEventListener('click', () => { file.value = ''; document.getElementById('file-label').textContent = 'Choose a file or drop it here'; document.getElementById('file-error').hidden = true; show(7); });
  file.addEventListener('change', () => {
    const chosen = file.files[0]; const error = document.getElementById('file-error');
    const invalid = chosen && (!/\.(pdf|doc|docx)$/i.test(chosen.name) || chosen.size > 5 * 1024 * 1024);
    error.hidden = !invalid; error.textContent = 'Please choose a PDF, DOC or DOCX file, 5 MB or smaller.';
    if (invalid) file.value = '';
    document.getElementById('file-label').textContent = file.files[0]?.name || 'Choose a file or drop it here';
  });
  form.addEventListener('submit', event => {
    if (current !== steps.length - 1) { event.preventDefault(); next.click(); }
    else { next.disabled = true; next.textContent = 'Saving your profile…'; }
  });
  form.addEventListener('invalid', event => {
    const index = steps.indexOf(event.target.closest('.setup-step'));
    if (index >= 0 && index !== current) show(index);
  }, true);
  show(0, false);
})();
