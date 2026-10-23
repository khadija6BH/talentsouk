/* Optional browser dictation: only finalized text enters the editable answer. */
(() => {
  const form = document.getElementById('mock-form');
  if (!form) return;
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  let active = null;
  function cancel() {
    if (!active) return;
    const previous = active;
    active = null;
    previous.recognition.abort();
    previous.start.disabled = false;
    previous.stop.disabled = true;
    previous.language.disabled = false;
    previous.message.textContent = 'Dictation stopped. Review your answer before submitting.';
  }
  function attach(area) {
    if (area.dataset.dictationReady) return;
    area.dataset.dictationReady = 'true';
    const box = document.createElement('div');
    box.className = 'rounded-xl border border-slate-200 p-3 mt-3';
    const label = document.createElement('label');
    label.className = 'text-sm font-semibold';
    label.textContent = 'Answer by voice (optional) ';
    const language = document.createElement('select');
    language.className = 'border border-slate-200 rounded-lg p-2 text-sm';
    language.setAttribute('aria-label', 'Dictation language');
    [['fr-FR', 'Français'], ['en-US', 'English'], ['ar-MA', 'العربية — Maroc']].forEach(([value, name]) => {
      const option = document.createElement('option');
      option.value = value; option.textContent = name; language.append(option);
    });
    label.append(language);
    const actions = document.createElement('div');
    actions.className = 'flex flex-wrap gap-2 mt-3';
    const start = document.createElement('button');
    start.type = 'button'; start.className = 'btn btn-secondary'; start.textContent = 'Dicter ma réponse';
    const stop = document.createElement('button');
    stop.type = 'button'; stop.className = 'btn btn-secondary'; stop.textContent = 'Stop'; stop.disabled = true;
    const notice = document.createElement('p');
    notice.className = 'text-xs text-slate-500 mt-3';
    notice.textContent = 'Your browser may send audio to its speech service. TalentSouk saves no audio. Only your reviewed text is submitted for feedback. Arabic and Darija accuracy depends on your browser.';
    const message = document.createElement('p');
    message.className = 'text-sm mt-2'; message.setAttribute('role', 'status'); message.setAttribute('aria-live', 'polite');
    if (!Speech) {
      start.disabled = true;
      message.textContent = 'Voice dictation is unavailable in this browser. Type your answer, or try a browser with speech recognition.';
    }
    actions.append(start, stop); box.append(label, actions, notice, message); area.after(box);
    start.addEventListener('click', () => {
      cancel();
      if (!Speech || !area.isConnected || area.closest('[hidden], .hidden')) return;
      const recognition = new Speech();
      recognition.lang = language.value; recognition.continuous = true; recognition.interimResults = true;
      const state = {recognition, area, start, stop, message, language}; active = state;
      start.disabled = true; stop.disabled = false; language.disabled = true;
      message.textContent = 'Allow microphone access to begin. Click Stop when finished.';
      recognition.onstart = () => { if (active === state) message.textContent = 'Listening… Speak your answer, then click Stop.'; };
      recognition.onresult = event => {
        if (active !== state || !area.isConnected || area.closest('[hidden], .hidden')) return;
        let pending = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const text = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            const joined = area.value + (area.value.trim() ? ' ' : '') + text.trim();
            const limit = area.maxLength > 0 ? area.maxLength : 6000;
            area.value = joined.slice(0, limit);
            area.dispatchEvent(new Event('input', {bubbles: true}));
            if (joined.length >= limit) {
              message.textContent = 'Answer length limit reached. Review the text.';
              recognition.stop();
              return;
            }
          } else pending += text;
        }
        message.textContent = pending ? 'Listening: ' + pending : 'Text added. Continue speaking or click Stop.';
      };
      recognition.onerror = event => {
        if (active !== state) return;
        const errors = {'not-allowed': 'Microphone access was denied. Allow it in browser settings or type your answer.',
          'audio-capture': 'No microphone is available. Type your answer.',
          'network': 'The speech service is unavailable. Your written answer is preserved.',
          'no-speech': 'No speech was detected. Try again or type your answer.',
          'language-not-supported': 'This language is unavailable. Choose another language or type your answer.'};
        message.textContent = errors[event.error] || 'Dictation ended. You can type or try again.';
        state.failed = true;
      };
      recognition.onend = () => {
        if (active !== state) return;
        active = null; start.disabled = false; stop.disabled = true; language.disabled = false;
        if (!state.failed) message.textContent = 'Dictation finished. Correct the text before requesting feedback.';
      };
      try { recognition.start(); } catch (error) {
        active = null; start.disabled = false; stop.disabled = true; language.disabled = false;
        message.textContent = 'Unable to start dictation. Type your answer or try again.';
      }
    });
    stop.addEventListener('click', () => { if (active?.area === area) { stop.disabled = true; message.textContent = 'Finishing dictation...'; active.recognition.stop(); } });
    // Editing deliberately stops dictation so delayed speech cannot alter a correction.
    area.addEventListener('keydown', cancel);
    area.addEventListener('paste', cancel);
  }
  function refresh() {
    if (active && (!active.area.isConnected || active.area.closest('[hidden], .hidden'))) cancel();
    form.querySelectorAll('.mock-answer').forEach(attach);
  }
  new MutationObserver(refresh).observe(document.getElementById('practice-panel') || form, {childList: true, subtree: true, attributes: true, attributeFilter: ['hidden', 'class']});
  document.querySelectorAll('.sim-tab, #complete-mock, #practice-start').forEach(button => button.addEventListener('click', cancel, true));
  window.addEventListener('pagehide', cancel);
  refresh();
})();
