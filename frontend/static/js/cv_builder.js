(() => {
  const config = window.CV_BUILDER_CONFIG || {};
  const offers = window.CV_BUILDER_OFFERS || [];
  const templates = window.CV_BUILDER_TEMPLATES || ["Modern", "Minimal", "Professional", "Tech / AI"];
  const fields = [
    "full_name", "job_title", "email", "phone", "linkedin", "github", "location", "accent_color", "summary", "education",
    "experience", "skills", "projects", "certifications", "languages",
  ];
  const elementIds = Object.fromEntries(fields.map((field) => [field, `cv-${field.replaceAll("_", "-")}`]));
  const defaultProfile = Object.fromEntries(fields.map((field) => [field, ""]));
  const profiles = { ...config.profiles };
  const sourceTemplates = { ...config.templates };
  const uploadedSourceButton = document.querySelector('.cv-source-button[data-source="uploaded"]');
  const hasUpload = Boolean(uploadedSourceButton && !uploadedSourceButton.disabled);
  let activeSource = hasUpload && config.initial_source === "uploaded" ? "uploaded" : "manual";
  let dirty = false;

  ["manual", "uploaded"].forEach((source) => {
    profiles[source] = { ...defaultProfile, ...(profiles[source] || {}) };
    sourceTemplates[source] = sourceTemplates[source] || "Modern";
  });

  const form = document.getElementById("cv-profile-form");
  const preview = document.getElementById("cv-preview");
  const templateSelect = document.getElementById("cv-template-select");
  const sourceNote = document.getElementById("cv-source-note");
  const saveStatus = document.getElementById("cv-save-status");
  const optimizerResults = document.getElementById("optimizer-results");
  const optimizerStatus = document.getElementById("optimizer-status");
  let profilePhotoUrl = String(config.profile_photo_url || "");

  function syncDesignControls(profile, template) {
    document.querySelectorAll(".cv-template-card").forEach((button) => {
      button.classList.toggle("is-selected", button.dataset.template === template);
    });
    document.querySelectorAll(".cv-color-option").forEach((button) => {
      button.classList.toggle("is-selected", button.dataset.color.toLowerCase() === String(profile.accent_color || "#673147").toLowerCase());
    });
  }

  function setStatus(node, message, state = "") {
    node.textContent = message;
    node.classList.toggle("is-success", state === "success");
    node.classList.toggle("is-error", state === "error");
  }

  function collectProfile() {
    return Object.fromEntries(fields.map((field) => [
      field,
      document.getElementById(elementIds[field]).value.trim(),
    ]));
  }

  document.addEventListener('cv-photo-change',event=>{
    if(typeof event.detail?.url!=='string')return;
    profilePhotoUrl=event.detail.url;
    renderPreview(preview,collectProfile(),templateSelect.value);
  });
  function renderPreview(target, profile, template) {
    target.replaceChildren();
    target.dataset.template = template;
    target.style.setProperty("--cv-accent", profile.accent_color || "#673147");

    const header = document.createElement("header");
    header.className = "cv-document-header";
    if (profilePhotoUrl && template !== "Minimal") {
      const photo = document.createElement("img");
      photo.className = "cv-document-photo";
      photo.src = profilePhotoUrl;
      photo.alt = "Candidate photo";
      header.append(photo);
    }
    const identity = document.createElement("div");
    identity.className = "cv-document-identity";
    const name = document.createElement("h2");
    name.className = "cv-document-name";
    name.textContent = profile.full_name || "Your Name";
    identity.append(name);
    if (profile.job_title) {
      const title = document.createElement("p");
      title.className = "cv-document-job-title";
      title.textContent = profile.job_title;
      identity.append(title);
    }
    const contactDetails = [profile.email, profile.phone, profile.location, profile.linkedin, profile.github].filter(Boolean);
    if (contactDetails.length) {
      const contact = document.createElement("div");
      contact.className = "cv-document-contact";
      contactDetails.forEach((detail) => {
        const item = document.createElement("span");
        item.textContent = detail;
        contact.append(item);
      });
      identity.append(contact);
    }
    header.append(identity);
    target.append(header);

    const sections = [
      ["Professional Summary", "summary", "paragraph"],
      ["Education", "education", "list"],
      ["Experience", "experience", "list"],
      ["Skills", "skills", "skills"],
      ["Projects", "projects", "list"],
      ["Certifications", "certifications", "list"],
      ["Languages", "languages", "list"],
    ];
    let sectionCount = 0;
    sections.forEach(([title, field, type]) => {
      const value = String(profile[field] || "").trim();
      if (!value) return;
      sectionCount += 1;
      const section = document.createElement("section");
      section.className = "cv-document-section";
      const heading = document.createElement("h3");
      heading.textContent = title;
      section.append(heading);

      if (type === "paragraph") {
        const paragraph = document.createElement("p");
        paragraph.textContent = value;
        section.append(paragraph);
      } else {
        const items = type === "skills"
          ? value.split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean)
          : value.split(/\n+/).map((item) => item.trim()).filter(Boolean);
        const list = document.createElement("ul");
        if (type === "skills") list.className = "cv-document-skills";
        items.forEach((item) => {
          const listItem = document.createElement("li");
          listItem.textContent = item;
          list.append(listItem);
        });
        section.append(list);
      }
      target.append(section);
    });

    if (!sectionCount) {
      const empty = document.createElement("p");
      empty.className = "cv-document-empty";
      empty.textContent = "Your CV sections will appear here as you add details.";
      target.append(empty);
    }
  }

  function loadEditor(source) {
    activeSource = source;
    const profile = profiles[source];
    if (!profile.accent_color) profile.accent_color = "#673147";
    fields.forEach((field) => {
      document.getElementById(elementIds[field]).value = profile[field] || "";
    });
    templateSelect.value = sourceTemplates[source];
    syncDesignControls(profile, sourceTemplates[source]);
    document.querySelectorAll(".cv-source-button").forEach((button) => {
      const isActive = button.dataset.source === source;
      button.setAttribute("aria-pressed", String(isActive));
    });
    sourceNote.textContent = source === "uploaded"
      ? "Editing a copy. Your original is preserved."
      : "Your editable CV.";
    dirty = false;
    renderPreview(preview, profile, sourceTemplates[source]);
    document.getElementById("cv-preview-template").textContent = sourceTemplates[source];
    updateCompletion();
  }

  async function sendJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "The request could not be completed.");
    return body;
  }

  async function saveProfile(source = activeSource, profile = null) {
    const currentProfile = profile || (source === activeSource ? collectProfile() : profiles[source]);
    const template = source === activeSource ? templateSelect.value : sourceTemplates[source];
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    if (source === activeSource) setStatus(saveStatus, "Saving...");
    try {
      const saved = await sendJson("/api/cv-builder/profile", {
        source,
        profile: currentProfile,
        template,
      });
      profiles[source] = { ...defaultProfile, ...saved.profile };
      sourceTemplates[source] = saved.template;
      if (source === activeSource) {
        dirty = false;
        setStatus(saveStatus, "Saved", "success");
      }
      return saved;
    } catch (error) {
      if (source === activeSource) setStatus(saveStatus, error.message, "error");
      throw error;
    } finally {
      button.disabled = false;
    }
  }

  function setKeywords(targetId, words, variant) {
    const target = document.getElementById(targetId);
    target.replaceChildren();
    if (!words || !words.length) {
      const none = document.createElement("span");
      none.className = "text-xs text-slate-400";
      none.textContent = "None";
      target.append(none);
      return;
    }
    words.forEach((word) => {
      const chip = document.createElement("span");
      chip.className = `cv-keyword ${variant || ""}`.trim();
      chip.textContent = word;
      target.append(chip);
    });
  }

  function renderOptimization(result) {
    const versionExport=document.getElementById('builder-version-export');
    if(versionExport) versionExport.href=result.version_id?'/cv-versions/'+result.version_id:'/cv-builder/optimized/print';

    document.getElementById("ats-score-before").textContent = `${result.ats_score_before ?? result.match_percent}%`;
    document.getElementById("ats-score-after").textContent = `${result.ats_score_after ?? result.match_percent}%`;
    const languageItems = result.language_improvements || [];
    document.getElementById("language-improvement-count").textContent = String(languageItems.length);
    document.getElementById("optimizer-summary").textContent = result.suggested_summary || "Keep your current factual summary.";
    document.getElementById("optimizer-language-improvements").textContent = languageItems.length
      ? languageItems.join(" ") : "No basic spacing or punctuation issues detected.";
    document.getElementById("optimizer-match-score").textContent = `${result.match_percent}%`;
    setKeywords("optimizer-existing", result.existing_keywords, "");
    setKeywords("optimizer-missing", result.missing_keywords, "is-missing");
    setKeywords("optimizer-recommended", result.recommended_keywords, "is-recommended");
    document.getElementById("optimizer-target-label").textContent =
      `${result.offer_title} at ${result.company_name} · ${result.generated_at ? "saved version" : "preview"}`;
    renderPreview(
      document.getElementById("optimized-cv-preview"),
      result.profile,
      result.template || "Modern",
    );
    optimizerResults.classList.remove("hidden");
  }

  async function updateEditorSource(source) {
    if (source === activeSource) return;
    if (dirty) {
      try {
        await saveProfile(activeSource);
      } catch (_error) {
        return;
      }
    }
    loadEditor(source);
  }

  document.querySelectorAll(".cv-source-button").forEach((button) => {
    if (button.dataset.source === "uploaded" && !hasUpload) {
      button.disabled = true;
      button.title = "Upload a CV first to use it as a starting point.";
    }
    button.addEventListener("click", () => updateEditorSource(button.dataset.source));
  });

  fields.forEach((field) => {
    document.getElementById(elementIds[field]).addEventListener("input", () => {
      profiles[activeSource] = collectProfile();
      dirty = true;
      setStatus(saveStatus, "Unsaved changes");
      renderPreview(preview, profiles[activeSource], templateSelect.value);
    });
  });

  document.getElementById("choose-manual-workflow")?.addEventListener("click", async () => {
    await updateEditorSource("manual");
    document.getElementById("cv-editor-workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.getElementById("choose-uploaded-workflow")?.addEventListener("click", async () => {
    if (!hasUpload) return;
    await updateEditorSource("uploaded");
    document.getElementById("cv-editor-workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.getElementById("review-extracted-cv")?.addEventListener("click", async () => {
    await updateEditorSource("uploaded");
    document.getElementById("cv-editor-workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.getElementById("keep-original-cv")?.addEventListener("click", () => {
    window.location.href = "/cv-builder?cv_source=uploaded#cv-optimizer-workspace";
  });

  document.querySelectorAll(".cv-choice-list button").forEach((button) => {
    button.addEventListener("click", () => {
      const target = document.getElementById(button.closest(".cv-choice-list").dataset.target);
      const values = target.value.split(/[\n,;]+/).map((value) => value.trim()).filter(Boolean);
      const choice = button.textContent.trim();
      const index = values.findIndex((value) => value.toLowerCase() === choice.toLowerCase());
      if (index >= 0) values.splice(index, 1); else values.push(choice);
      target.value = values.join(", ");
      button.classList.toggle("is-selected", index < 0);
      target.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });

  templateSelect.addEventListener("change", () => {
    sourceTemplates[activeSource] = templateSelect.value;
    dirty = true;
    setStatus(saveStatus, "Unsaved changes");
    document.getElementById("cv-preview-template").textContent = templateSelect.value;
    renderPreview(preview, collectProfile(), templateSelect.value);
    syncDesignControls(collectProfile(), templateSelect.value);
  });

  document.querySelectorAll(".cv-template-card").forEach((button) => {
    button.addEventListener("click", () => {
      templateSelect.value = button.dataset.template;
      templateSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  document.querySelectorAll(".cv-color-option").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById("cv-accent-color").value = button.dataset.color;
      document.getElementById("cv-accent-color").dispatchEvent(new Event("input", { bubbles: true }));
      syncDesignControls(collectProfile(), templateSelect.value);
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await saveProfile(activeSource, collectProfile());
    } catch (_error) {
      // The save status already contains the server error.
    }
  });

  const summaryModal = document.getElementById("summary-options-modal");
  const summaryOptions = document.getElementById("summary-options");
  const summaryStatus = document.getElementById("summary-ai-status");
  document.getElementById("generate-summary-button").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Generating…";
    summaryStatus.textContent = "Creating three factual ATS summary options…";
    try {
      const data = await sendJson("/api/cv-builder/generate-summary", {
        profile: collectProfile(),
        language: document.getElementById("summary-language").value,
      });
      const labels = ["ATS-focused", "Professional", "Skills-focused"];
      summaryOptions.replaceChildren();
      data.summaries.forEach((summary, index) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "border border-slate-200 rounded-xl p-4 text-left bg-white hover:border-purple-300 hover:shadow-md transition flex flex-col";
        const title = document.createElement("strong");
        title.className = "text-slate-800";
        title.textContent = `${index + 1}. ${labels[index] || "Alternative"}`;
        const text = document.createElement("span");
        text.className = "text-sm text-slate-600 mt-3 flex-1";
        text.textContent = summary;
        const choose = document.createElement("span");
        choose.className = "btn btn-primary text-xs mt-4 justify-center";
        choose.textContent = "Choose this summary";
        option.append(title, text, choose);
        option.addEventListener("click", () => {
          const summaryField = document.getElementById("cv-summary");
          summaryField.value = summary;
          summaryField.dispatchEvent(new Event("input", { bubbles: true }));
          summaryModal.classList.add("hidden");
          summaryStatus.textContent = `${labels[index]} summary selected · ${data.provider} · ${data.model}. Review before saving.`;
        });
        summaryOptions.append(option);
      });
      summaryModal.classList.remove("hidden");
      summaryStatus.textContent = "Choose one of the generated summary options.";
    } catch (error) {
      summaryStatus.textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = "Generate with AI";
    }
  });
  document.getElementById("summary-options-close").addEventListener("click", () => summaryModal.classList.add("hidden"));
  document.getElementById("summary-options-backdrop").addEventListener("click", () => summaryModal.classList.add("hidden"));


  const experienceField = document.getElementById('cv-experience');
  const experienceStatus = document.getElementById('experience-ai-status');
  const experienceReview = document.getElementById('experience-ai-review');
  let experienceDraft = '', experienceOriginal = '', experienceSource = '';
  document.getElementById('experience-generate-ai').addEventListener('click', async event => {
    const button = event.currentTarget;
    if (!experienceField.value.trim()) {
      experienceStatus.textContent = 'Describe your experience first. A few notes are enough to start.';
      experienceField.focus(); return;
    }
    experienceOriginal = experienceField.value; experienceSource = activeSource;
    experienceDraft = ''; experienceReview.hidden = true;
    button.disabled = true; button.textContent = '✧ Writing…';
    experienceStatus.textContent = 'Turning your notes into a professional CV entry…';
    try {
      const data = await sendJson('/api/cv-builder/improve-experience', {
        experience: experienceOriginal,
        language: document.getElementById('experience-ai-language').value,
      });
      experienceDraft = data.experience;
      document.getElementById('experience-ai-result').textContent = experienceDraft;
      experienceReview.hidden = false;
      experienceStatus.textContent = 'Your version is ready. Review it before applying.';
    } catch (error) { experienceStatus.textContent = error.message; }
    finally { button.disabled = false; button.textContent = '✧ Generate with AI'; }
  });
  document.getElementById('experience-ai-apply').addEventListener('click', () => {
    if (!experienceDraft) return;
    if (experienceSource !== activeSource || experienceField.value !== experienceOriginal) {
      experienceStatus.textContent = 'Your text or CV source has changed. Generate a new version to keep your latest edits.';
      experienceReview.hidden = true; return;
    }
    experienceField.value = experienceDraft;
    experienceField.dispatchEvent(new Event('input', {bubbles:true}));
    experienceReview.hidden = true; experienceDraft = '';
    experienceStatus.textContent = 'Professional version applied. Save CV when you are ready.';
  });
  document.getElementById('experience-ai-cancel').addEventListener('click', () => {
    experienceDraft = ''; experienceReview.hidden = true;
    experienceStatus.textContent = 'Your original text is unchanged.';
  });

  function addSectionAssistant(section, host, getText, applyText, title = 'Generate with AI') {
    const toolbar = document.createElement('div'); toolbar.className = 'cv-section-ai';
    const language = document.createElement('select'); language.setAttribute('aria-label', 'AI language');
    for (const [value, label] of [['en','English'],['fr','Français'],['ar','العربية']]) {
      const option=document.createElement('option');option.value=value;option.textContent=label;language.append(option);
    }
    const button=document.createElement('button');button.type='button';button.className='cv-ai-write-button';button.textContent='✧ '+title;
    const status=document.createElement('p');status.className='cv-section-ai-status';status.setAttribute('role','status');
    const review=document.createElement('div');review.className='cv-experience-review';review.hidden=true;
    const result=document.createElement('pre');result.dir='auto';
    const actions=document.createElement('div');
    const accept=document.createElement('button');accept.type='button';accept.className='btn btn-primary';accept.textContent='Apply';
    const cancel=document.createElement('button');cancel.type='button';cancel.className='btn btn-ghost';cancel.textContent='Keep original';
    actions.append(accept,cancel);review.append(result,actions);toolbar.append(language,button);host.append(toolbar,status,review);
    let draft='', original='', source='';
    button.addEventListener('click',async()=>{
      original=getText();source=activeSource;review.hidden=true;draft='';
      if(!original.trim()){status.textContent='Add a few notes first.';return;}
      button.disabled=true;status.textContent='Writing…';
      try{
        const response=await sendJson('/api/cv-builder/improve-section',{section,text:original,language:language.value});
        draft=response.text;result.textContent=draft;review.hidden=false;status.textContent='Review your draft.';
      }catch(error){status.textContent=error.message;}
      finally{button.disabled=false;}
    });
    accept.addEventListener('click',()=>{
      if(!draft)return;
      if(source!==activeSource || getText()!==original){status.textContent='Details changed. Generate a fresh draft.';review.hidden=true;return;}
      applyText(draft);review.hidden=true;draft='';status.textContent='Applied. Save when ready.';
    });
    cancel.addEventListener('click',()=>{draft='';review.hidden=true;status.textContent='Original kept.';});
  }
  for(const section of ['job_title','education','skills','projects','certifications','languages']){
    const field=document.getElementById(elementIds[section]);
    const host=section==='job_title'?field.closest('.cv-personal-fields'):field.closest('.cv-field');
    addSectionAssistant(section,host,()=>field.value,value=>{
      field.value=value;field.dispatchEvent(new Event('input',{bubbles:true}));
    },section==='job_title'?'Polish target role':'Generate with AI');
  }
  addSectionAssistant('design',document.querySelector('.cv-design-panel'),()=>[collectProfile().job_title,collectProfile().skills].filter(Boolean).join(' · '),value=>{
    templateSelect.value=value;templateSelect.dispatchEvent(new Event('change',{bubbles:true}));
  },'Suggest a template');

  // A focused editor keeps every existing field and save action intact.
  const editor = document.querySelector('.cv-editor-panel');
  const groupDefinitions = [
    ['cv-full-name', 'Personal details', 'Add your contact details.'],
    ['cv-summary', 'Professional summary', 'A short introduction.'],
    ['cv-education', 'Education', 'Qualifications, schools and dates.'],
    ['cv-skills', 'Skills', 'Add your strongest skills.'],
    ['cv-experience', 'Experience', 'Your notes, professionally written.'],
    ['cv-projects', 'Projects', 'What you built and contributed.'],
    ['cv-certifications', 'Certifications', 'Qualifications you have earned.'],
    ['cv-languages', 'Languages', 'Languages and proficiency.'],
  ];
  const personal = document.getElementById('cv-full-name').closest('.cv-personal-fields');
  const finalPair = document.getElementById('cv-certifications').closest('.cv-personal-fields');
  const groups = [personal, document.getElementById('cv-summary').parentElement,
    ...['cv-education','cv-skills','cv-experience','cv-projects'].map(id=>document.getElementById(id).closest('.cv-field')),
    finalPair.querySelector('label'), finalPair.querySelectorAll('label')[1]];
  const design = document.querySelector('.cv-design-panel');
  let selectedStep = 0;
  function selectStep(index) {
    selectedStep = index;
    groups.forEach((group,i)=>group.hidden=i!==index);
    design.hidden = true;
    document.getElementById('cv-step-label').textContent = 'SECTION '+String(index+1).padStart(2,'0');
    document.getElementById('cv-step-title').textContent = groupDefinitions[index][1];
    document.getElementById('cv-step-description').textContent = groupDefinitions[index][2];
    document.querySelectorAll('.cv-section-nav button[data-focus]').forEach(button=>{
      const active=button.dataset.focus===groupDefinitions[index][0];
      button.classList.toggle('is-active',active); button.setAttribute('aria-current',active?'step':'false');
    });
  }
  document.querySelectorAll('.cv-section-nav button[data-focus]').forEach(button=>{
    button.addEventListener('click',()=>{
      selectStep(groupDefinitions.findIndex(group=>group[0]===button.dataset.focus));
      document.getElementById(button.dataset.focus).focus({preventScroll:true});
    });
  });
  const nextButton=document.createElement('button'); nextButton.type='button';nextButton.className='btn btn-secondary';nextButton.textContent='Next section →';
  nextButton.addEventListener('click',()=>selectStep((selectedStep+1)%groups.length));
  document.querySelector('.cv-save-actions').prepend(nextButton);
  const designButton=document.createElement('button');designButton.type='button';designButton.textContent='✧ Design & template';
  designButton.addEventListener('click',()=>{
    groups.forEach(group=>group.hidden=true);design.hidden=false;
    document.getElementById('cv-step-label').textContent='THE FINISHING TOUCH';
    document.getElementById('cv-step-title').textContent='Design & template';
    document.getElementById('cv-step-description').textContent='Choose a layout and color.';
    document.querySelectorAll('.cv-section-nav button').forEach(button=>button.classList.toggle('is-active',button===designButton));
  });
  document.querySelector('.cv-section-nav').insertBefore(designButton,document.querySelector('.cv-ats-note'));
  const exportButton=document.createElement('button');exportButton.type='button';exportButton.className='btn btn-primary cv-export-button';exportButton.textContent='Export PDF ↗';
  exportButton.addEventListener('click',()=>window.print());
  document.querySelector('.cv-preview-heading').append(exportButton);
  function updateCompletion(){
    const values=collectProfile();
    const keys=['full_name','job_title','email','summary','experience','education','skills','projects','certifications','languages'];
    const percent=Math.round(keys.filter(key=>Boolean(values[key])).length/keys.length*100);
    document.getElementById('cv-completion-value').textContent=percent+'%';
    document.getElementById('cv-completion-progress').value=percent;
    document.querySelectorAll('.cv-section-nav button[data-focus]').forEach(button=>{
      button.classList.toggle('is-complete',Boolean(document.getElementById(button.dataset.focus).value.trim()));
    });
  }
  form.addEventListener('input',updateCompletion);
  const aiPanel=document.getElementById('cv-ai-studio');
  function setMode(ai){
    aiPanel.hidden=!ai;
    document.getElementById('tab-panel-cv').hidden=ai;
    document.querySelector('.cv-workflow-shortcuts').hidden=ai;
    document.querySelectorAll('.cv-mode-bar button').forEach(button=>{
      const active=ai?button.id==='studio-ai-mode':button.id==='studio-edit-mode';
      button.classList.toggle('is-active',active);button.setAttribute('aria-pressed',String(active));
    });
    if(ai)document.getElementById('ai-target-role').value=collectProfile().job_title;
  }
  document.getElementById('studio-edit-mode').addEventListener('click',()=>setMode(false));
  document.getElementById('studio-ai-mode').addEventListener('click',()=>setMode(true));
  document.querySelector('.cv-mode-bar a').addEventListener('click',()=>setMode(false));
  let generatedDraft=null;
  document.getElementById('ai-generate-cv').addEventListener('click',async event=>{
    const button=event.currentTarget, status=document.getElementById('ai-cv-status');
    const draftProfile=collectProfile();draftProfile.job_title=document.getElementById('ai-target-role').value.trim();
    generatedDraft=null;document.getElementById('ai-cv-review').hidden=true;
    button.disabled=true;status.textContent='Shaping your story into a CV draft…';
    try{
      const result=await sendJson('/api/cv-builder/generate',{profile:draftProfile,notes:document.getElementById('ai-career-story').value,language:document.getElementById('ai-cv-language').value});
      generatedDraft=result.profile;
      document.getElementById('ai-cv-draft-text').textContent=['summary','experience','education','skills','projects','certifications','languages'].filter(key=>generatedDraft[key]).map(key=>key.toUpperCase()+'\n'+generatedDraft[key]).join('\n\n');
      document.getElementById('ai-cv-review').hidden=false;
      status.textContent='Draft generated. Review your details below before applying.';
    }catch(error){status.textContent=error.message;}
    finally{button.disabled=false;}
  });
  document.getElementById('ai-use-draft').addEventListener('click',()=>{
    if(!generatedDraft)return;
    fields.forEach(field=>document.getElementById(elementIds[field]).value=generatedDraft[field]||'');
    profiles[activeSource]=collectProfile();dirty=true;setStatus(saveStatus,'AI draft applied · Review and save');
    renderPreview(preview,profiles[activeSource],templateSelect.value);
    setMode(false);selectStep(1);updateCompletion();
    document.getElementById('cv-editor-workspace').scrollIntoView({behavior:'smooth'});
  });
  document.getElementById('ai-discard-draft').addEventListener('click',()=>{
    generatedDraft=null;document.getElementById('ai-cv-review').hidden=true;document.getElementById('ai-cv-status').textContent='Draft discarded. Your CV is unchanged.';
  });
  selectStep(0);
  if (window.location.hash === "#manual" || window.location.hash === "#create") activeSource = "manual";
  if (window.location.hash === "#uploaded" && hasUpload) activeSource = "uploaded";
  loadEditor(activeSource);
  updateCompletion();
})();
