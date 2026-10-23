(() => {
  const form = document.getElementById("postulation-form");
  if (!form) return;
  const workspace = document.getElementById("postulation-workspace");

  const company = document.getElementById("company-id");
  const job = document.getElementById("job-id");
  const position = document.getElementById("position");
  const positionGroup = document.getElementById("position-group");
  const cv = document.getElementById("cv-choice");
  const message = document.getElementById("application-message");
  const coverLetter = document.getElementById("cover-letter");
  const generateCoverLetter = document.getElementById("generate-cover-letter");
  const coverLetterStatus = document.getElementById("cover-letter-status");
  const preview = document.getElementById("postulation-preview");
  const error = document.getElementById("postulation-error");
  const save = document.getElementById("save-postulation");
  let reviewedPayload = null;
  let savedDraft = null;
  let savingDraft = null;
  let previewVersion = 0;

  const selectedText = (select) => select.options[select.selectedIndex]?.textContent.trim() || "";
  const showError = (text) => {
    error.textContent = text;
    error.classList.toggle("hidden", !text);
  };
  const invalidatePreview = () => {
    reviewedPayload = null;
    previewVersion++;
    preview.classList.add("hidden");
    document.getElementById("postulation-guide")?.classList.remove("hidden");
    document.getElementById("postulation-success").classList.add("hidden");
  };
  const syncOfferMode = () => {
    const hasOffer = Boolean(job.value);
    positionGroup.classList.toggle("hidden", hasOffer);
    position.required = !hasOffer;
  };

  job.addEventListener("change", () => {
    const option = job.options[job.selectedIndex];
    if (job.value && option.dataset.companyId) company.value = option.dataset.companyId;
    syncOfferMode();
  });
  form.addEventListener("input", invalidatePreview);
  form.addEventListener("change", invalidatePreview);
  message.addEventListener("input", () => {
    document.getElementById("message-count").textContent = message.value.length;
  });

  const generateMessage = document.getElementById("generate-application-message");
  const messageStatus = document.getElementById("application-message-status");
  generateMessage.addEventListener("click", async () => {
    showError("");
    if (!company.value || !cv.value || (!job.value && !position.value.trim())) return showError("Choose a company, CV and target position first.");
    if (message.value.trim() && !window.confirm("Replace your current message with a new AI draft?")) return;
    generateMessage.disabled = true;
    generateMessage.textContent = "Generating…";
    messageStatus.textContent = "Creating your message from the selected CV and offer…";
    const context = JSON.stringify([company.value, job.value, cv.value, position.value, document.getElementById("draft-language").value]);
    const previous = message.value;
    try {
      const response = await fetch("/api/postulations/message", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({company_id:company.value,job_id:job.value || null,cv:cv.value,position:position.value.trim(),language:document.getElementById("draft-language").value})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Unable to generate the message.");
      if (context !== JSON.stringify([company.value, job.value, cv.value, position.value, document.getElementById("draft-language").value]) || previous !== message.value) throw new Error("Your inputs changed. Generate again for the current application.");
      if (message.disabled) throw new Error("The reviewed application is already being saved. The new draft was not applied.");
      message.value = result.message.slice(0,5000);
      message.dispatchEvent(new Event("input", {bubbles:true}));
      messageStatus.textContent = "Draft ready. Review and edit it before previewing.";
      message.focus();
    } catch (error) {messageStatus.textContent = error.message;}
    finally {generateMessage.disabled=false;generateMessage.textContent="✦ Generate message with AI";}
  });

  generateCoverLetter?.addEventListener("click", async () => {
    showError("");
    if (!company.value) return showError("Choose a company before generating a cover letter.");
    if (!job.value && !position.value.trim()) return showError("Enter a target position for a spontaneous application.");
    if (!cv.value) return showError("Choose one of your CVs before generating a cover letter.");
    generateCoverLetter.disabled = true;
    generateCoverLetter.textContent = "Generating...";
    coverLetterStatus.textContent = "Creating a draft from your saved CV information...";
    try {
      const response = await fetch("/api/postulations/cover-letter", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_id: company.value,
          job_id: job.value || null,
          position: position.value.trim(),
          cv: cv.value,
          language: document.getElementById("draft-language").value,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The cover letter could not be generated.");
      if (coverLetter.disabled) throw new Error("The reviewed application is already being saved. The new letter was not applied.");
      coverLetter.value = result.cover_letter;
      coverLetter.dispatchEvent(new Event("input", { bubbles: true }));
      coverLetterStatus.textContent = "Draft generated from saved evidence. Review and edit it before previewing.";
      coverLetter.focus();
    } catch (requestError) {
      coverLetterStatus.textContent = requestError.message;
    } finally {
      generateCoverLetter.disabled = false;
      generateCoverLetter.textContent = "Generate with AI";
    }
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    showError("");
    const payload = {
      company_id: company.value,
      job_id: job.value || null,
      position: position.value.trim(),
      cv: cv.value,
      message: message.value.trim(),
      cover_letter: coverLetter.value.trim(),
    };
    if (!payload.company_id) return showError("Choose a company.");
    if (!payload.job_id && !payload.position) return showError("Enter a target position for a spontaneous application.");
    if (!payload.cv) return showError("Choose one of your CVs.");
    if (!payload.message) return showError("Write an application message.");

    reviewedPayload = payload;
    document.getElementById("preview-company").textContent = selectedText(company);
    document.getElementById("preview-position").textContent = payload.job_id ? selectedText(job) : `Spontaneous — ${payload.position}`;
    document.getElementById("preview-cv").textContent = selectedText(cv);
    document.getElementById("preview-message").textContent = payload.message;
    const coverPreviewGroup = document.getElementById("preview-cover-letter-group");
    document.getElementById("preview-cover-letter").textContent = payload.cover_letter;
    coverPreviewGroup.classList.toggle("hidden", !payload.cover_letter);
    preview.classList.remove("hidden");
    document.getElementById("postulation-guide")?.classList.add("hidden");
    loadDeliveryChannels(payload, ++previewVersion);
    preview.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  async function persistDraft() {
    if (savedDraft) return savedDraft;
    if (savingDraft) return savingDraft;
    const payload = reviewedPayload;
    if (!payload) throw new Error("Preview your application first.");
    // Freeze reviewed inputs while saving to keep the email and its attachments bound.
    form.querySelectorAll("input,select,textarea,button").forEach(control => control.disabled = true);
    savingDraft = (async () => {
      const response = await fetch("/api/postulations", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Unable to save your application.");
      savedDraft = result;
      return result;
    })();
    try {return await savingDraft;}
    catch (error) {form.querySelectorAll("input,select,textarea,button").forEach(control => control.disabled=false);throw error;}
    finally {savingDraft=null;}
  }

  function savedResult(text, url) {
    const success=document.getElementById("postulation-success");
    success.textContent=text;success.classList.remove("hidden");
    if (!document.getElementById("saved-application-link")) {
      const link=viewApplicationsLink(url);link.id="saved-application-link";preview.append(link);
    }
    save.textContent="Application saved";save.disabled=true;
  }

  save.addEventListener("click", async () => {
    showError("");save.disabled=true;save.textContent="Saving…";
    try {const result=await persistDraft();savedResult(result.message,result.applications_url);}
    catch (error) {showError(error.message);save.disabled=false;save.textContent="Save application";}
  });

  async function loadDeliveryChannels(payload, version) {
    const actions=document.getElementById("delivery-channel-actions");
    const status=document.getElementById("delivery-channel-status");
    actions.replaceChildren();status.textContent="Checking available contact details…";
    try {
      const response=await fetch("/api/postulations/channels",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      const channels=await response.json();
      if (version!==previewVersion) return;
      if (!response.ok) throw new Error(channels.error || "Unable to check contact details.");
      let count=0;
      if (channels.email) {
        const target=document.createElement("p");target.className="text-sm";target.textContent="Email recipient: "+channels.email;actions.append(target);
        if (channels.gmail_connected) {
          const button=document.createElement("button");button.type="button";button.className="btn btn-primary w-full";button.textContent="Send with Gmail & save application";
          button.addEventListener("click",async () => {
            if (!payload.cover_letter) return showError("Add a cover letter and preview again before Gmail sending.");
            if (!window.confirm("Send this reviewed application to "+channels.email+" through Gmail now? Your selected CV and final cover letter will be attached, and the application will be saved.")) return;
            button.disabled=true;save.disabled=true;button.textContent="Sending…";showError("");
            try {
              const draft=await persistDraft();
              const response=await fetch(`/api/postulations/${draft.application.id}/send`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirmed:true})});
              const sent=await response.json();
              if (!response.ok) throw new Error(sent.error || "Gmail could not send the application.");
              savedResult(sent.message,sent.applications_url);button.textContent="Sent through Gmail";
            } catch(error) {
              showError(error.message+(savedDraft ? " Your draft is saved; retry sending without creating another application." : ""));
              button.disabled=false;button.textContent="Retry Gmail sending";save.disabled=Boolean(savedDraft);save.textContent=savedDraft ? "Application saved as draft" : "Save application";
              if(savedDraft) savedResult("Draft saved. Gmail sending was not confirmed as successful.",savedDraft.applications_url);
            }
          });actions.append(button);count++;
        } else if(channels.gmail_configured) {
          const link=document.createElement("a");link.className="btn btn-secondary w-full";link.href=workspace.dataset.gmailConnectUrl+"?next=applications";link.textContent="Save draft & connect Gmail";
          link.addEventListener("click",async event => {event.preventDefault();showError("");try{const draft=await persistDraft();savedResult("Draft saved. Connect Gmail, then open the draft in Applications to send.",draft.applications_url);window.location.assign(link.href);}catch(error){showError(error.message);}});
          actions.append(link);count++;
        } else {const note=document.createElement("p");note.className="text-sm";note.textContent="Gmail sending is not configured. Use an available external channel below.";actions.append(note);}
      }
      if(channels.whatsapp_number) {
        const link=document.createElement("a");link.className="btn btn-secondary w-full";link.target="_blank";link.rel="noopener noreferrer";
        link.href="https://wa.me/"+channels.whatsapp_number+"?text="+encodeURIComponent(payload.message);
        link.textContent="Open WhatsApp · +"+channels.whatsapp_number;actions.append(link);count++;
      }
      if(channels.offer_url) {
        const link=document.createElement("a");link.className="btn btn-secondary w-full";link.target="_blank";link.rel="noopener noreferrer";link.href=channels.offer_url;link.textContent="Apply on the original offer website ↗";actions.append(link);count++;
      }
      status.textContent=count ? "Choose an available channel below, or save your draft." : "No usable email, international phone number or offer link is available. You can save your draft.";
    } catch(error) {if(version===previewVersion)status.textContent=error.message+" You can still save your draft.";}
  }

  function viewApplicationsLink(url) {
    const link = document.createElement("a");
    link.href = url;
    link.className = "btn btn-ghost w-full";
    link.textContent = "View applications";
    return link;
  }

  const studioLink=document.getElementById('studio-cover-link');
  studioLink?.addEventListener('click',event=>{
    event.preventDefault();const query=new URLSearchParams({tab:'cover',company_id:company.value,offer_id:job.value});
    location.href='/ai-studio?'+query.toString();
  });
  try{
    const text=sessionStorage.getItem('studio-cover-draft');
    if(text){const draft=JSON.parse(text);const target=new URLSearchParams(location.search).get('company_id');
      if(draft.company_id===target&&typeof draft.text==='string'){
        if([...company.options].some(o=>o.value===target))company.value=target;
        const offerTarget=new URLSearchParams(location.search).get('offer_id');
        if([...job.options].some(o=>o.value===offerTarget))job.value=offerTarget;
        coverLetter.value=draft.text.slice(0,15000);coverLetterStatus.textContent='Draft from AI Studio. Review before sending.';
        sessionStorage.removeItem('studio-cover-draft');
      }
    }
  }catch{}
  syncOfferMode();
})();
