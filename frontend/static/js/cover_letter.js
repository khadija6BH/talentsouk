(() => {
  const companySelect = document.getElementById("cover-letter-company");
  const positionInput = document.getElementById("cover-letter-position");
  const offerSelect = document.getElementById("cover-letter-offer");
  const cvSourceSelect = document.getElementById("cover-letter-cv-source");
  const languageSelect = document.getElementById("cover-letter-language");
  const documentPreview = document.getElementById("cover-letter-document");
  const result = document.getElementById("cover-letter-result");
  const status = document.getElementById("cover-letter-status");
  const generateButton = document.getElementById("generate-cover-letter");
  const regenerateButton = document.getElementById("regenerate-cover-letter");
  const editButton = document.getElementById("edit-cover-letter");
  const copyButton = document.getElementById("copy-cover-letter");
  const downloadButton = document.getElementById("download-cover-letter");
  let latestLetter = "";
  let latestTarget = "";

  function setStatus(message, state = "") {
    status.textContent = message;
    status.classList.toggle("is-success", state === "success");
    status.classList.toggle("is-error", state === "error");
  }

  function selectedOffer() {
    return offerSelect.selectedOptions[0] || null;
  }

  const initialOfferId = offerSelect.value;
  const allOfferOptions = [...offerSelect.options].map((opt) => opt.cloneNode(true));

  function syncOffers(resetPosition) {
    const selectedCompany = companySelect.value;
    const matches = allOfferOptions
      .filter((option) => option.dataset.companyId === selectedCompany)
      .map((opt) => opt.cloneNode(true));
    const spontaneous = new Option("No published offer — spontaneous application", "");
    spontaneous.dataset.companyId = selectedCompany;
    offerSelect.replaceChildren(spontaneous, ...matches);
    offerSelect.disabled = false;
    if (matches.length && resetPosition) positionInput.value = matches[0].textContent;
    if (!matches.length && resetPosition) positionInput.value = "";
  }

  async function generate() {
    if (!companySelect.value || !positionInput.value.trim()) {
      setStatus("Choose a company, then enter a position.", "error");
      return;
    }

    generateButton.disabled = true;
    regenerateButton.disabled = true;
    setStatus("Generating your draft...");
    try {
      const response = await fetch("/api/cover-letter/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_id: companySelect.value,
          offer_id: offerSelect.value,
          position: positionInput.value.trim(),
          cv_source: cvSourceSelect.value,
          language: languageSelect.value,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The cover letter could not be generated.");

      latestLetter = data.letter;
      latestTarget = `${data.position} · ${data.company_name}`;
      documentPreview.textContent = latestLetter;
      documentPreview.contentEditable = "false";
      document.getElementById("cover-letter-document-target").textContent = latestTarget;
      result.classList.remove("hidden");
      regenerateButton.hidden = false;
      editButton.disabled = false;
      copyButton.disabled = false;
      downloadButton.disabled = false;
      editButton.textContent = "Edit";
      setStatus("Draft generated. Review and edit it before use.", "success");
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      generateButton.disabled = false;
      regenerateButton.disabled = false;
    }
  }

  async function copyLetter() {
    const text = documentPreview.innerText.trim();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch (_error) {
      const fallback = document.createElement("textarea");
      fallback.value = text;
      fallback.setAttribute("readonly", "");
      fallback.style.position = "fixed";
      fallback.style.opacity = "0";
      document.body.append(fallback);
      fallback.select();
      document.execCommand("copy");
      fallback.remove();
    }
    latestLetter = text;
    setStatus("Cover letter copied.", "success");
  }

  function downloadLetter() {
    const text = documentPreview.innerText.trim();
    if (!text) return;
    const filename = latestTarget
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "cover-letter";
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${filename}.txt`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    latestLetter = text;
    setStatus("Cover letter downloaded.", "success");
  }

  companySelect.addEventListener("change", () => {
    syncOffers(true);
    setStatus("Selections changed. Generate a new cover letter.");
  });
  offerSelect.addEventListener("change", () => {
    const offer = selectedOffer();
    if (offer?.value) positionInput.value = offer.textContent;
    setStatus("Selections changed. Generate a new cover letter.");
  });
  [positionInput, cvSourceSelect, languageSelect].forEach((control) => {
    control.addEventListener("input", () => setStatus("Selections changed. Generate a new cover letter."));
    control.addEventListener("change", () => setStatus("Selections changed. Generate a new cover letter."));
  });
  generateButton.addEventListener("click", generate);
  regenerateButton.addEventListener("click", generate);
  editButton.addEventListener("click", () => {
    const isEditing = documentPreview.contentEditable === "true";
    documentPreview.contentEditable = String(!isEditing);
    editButton.textContent = isEditing ? "Edit" : "Done editing";
    if (isEditing) {
      latestLetter = documentPreview.innerText.trim();
      setStatus("Edits applied to this draft.", "success");
    } else {
      documentPreview.focus();
      setStatus("Edit the letter directly in the document.");
    }
  });
  copyButton.addEventListener("click", copyLetter);
  downloadButton.addEventListener("click", downloadLetter);

  syncOffers(true);
  if (initialOfferId && [...offerSelect.options].some(option => option.value === initialOfferId)) {
    offerSelect.value = initialOfferId;
    positionInput.value = selectedOffer()?.textContent || positionInput.value;
  }
})();
