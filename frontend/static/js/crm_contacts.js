(() => {
  const statuses = window.APPLICATION_STATUSES;
  const applicationsUrl = "/api/crm";
  const board = document.getElementById("crm-board");
  const dialog = document.getElementById("application-dialog");
  const form = document.getElementById("application-form");
  const applications = [];
  const companyOptions = [...document.getElementById("application-company").options]
    .filter((option) => option.value)
    .reduce((companies, option) => {
      companies[option.value] = {
        category: option.dataset.category || "",
        domains: JSON.parse(option.dataset.domains || '[]'),
        url: option.dataset.url || "",
      };
      return companies;
    }, {});

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function showError(message, formError = false) {
    const target = document.getElementById(formError ? "application-form-error" : "crm-error");
    target.textContent = message;
    target.classList.remove("hidden");
  }

  function clearError(formError = false) {
    const target = document.getElementById(formError ? "application-form-error" : "crm-error");
    target.textContent = "";
    target.classList.add("hidden");
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "The CRM record could not be saved.");
    return body;
  }

  function formatDate(value) {
    if (!value) return "Not recorded";
    const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime())
      ? value
      : new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" }).format(date);
  }

  function updateCategoryFilter() {
    const select = document.getElementById("crm-category-filter");
    const selected = select.value;
    const categories = [...new Set(['Génie civil','Construction / BTP',...applications.flatMap(item=>companyOptions[String(item.company_id)]?.domains||[item.category])])].filter(Boolean).sort();
    select.replaceChildren(new Option("All categories", "all"));
    categories.forEach((category) => select.add(new Option(category, category)));
    if (categories.includes(selected)) select.value = selected;
  }

  const statusFilter = document.getElementById("crm-status-filter");
  statuses.forEach((status) => statusFilter.add(new Option(status, status)));

  function filteredApplications() {
    const query = document.getElementById("crm-search").value.trim().toLocaleLowerCase();
    const status = document.getElementById("crm-status-filter").value;
    const category = document.getElementById("crm-category-filter").value;
    return applications.filter((item) => {
      const searchable = [item.company_name, item.contact_email, item.notes]
        .join(" ").toLocaleLowerCase();
      return (!query || searchable.includes(query))
        && (status === "all" || item.status === status)
        && (category === "all" || (companyOptions[String(item.company_id)]?.domains||[item.category]).includes(category));
    });
  }

  function addDetail(parent, label, value, href) {
    const row = element("div", "crm-detail-row");
    row.append(element("span", "crm-detail-label", label));
    const content = href && value
      ? element("a", "crm-detail-value crm-email", value)
      : element("span", "crm-detail-value", value || "Not recorded");
    if (href && value) content.href = href;
    row.append(content);
    parent.append(row);
  }

  let selectedId = null;
  const detail = document.getElementById('contact-detail');
  const initials = item => (item.company_name || '?').split(/\s+/).slice(0,2).map(w=>w[0]).join('').toUpperCase();
  const label = item => item.contact_email || item.company_name;
  function renderDetails(item) {
    detail.replaceChildren();
    if(!item){detail.append(element('p','relation-empty','Select a contact to view details.'));return;}
    const top=element('div','relation-detail-header');
    top.append(element('div','relation-avatar',initials(item)),element('h2','',label(item)),element('p','subtitle',item.company_name));
    const actions=element('div','relation-actions');
    if(item.contact_email){const email=element('a','','Email');email.href='mailto:'+item.contact_email;actions.append(email);}
    if(!item.read_only){const edit=element('button','','Edit contact');edit.type='button';edit.addEventListener('click',()=>openEditor(item));actions.append(edit);}
    top.append(actions);detail.append(top);
    const fields=element('dl','relation-fields');
    for(const [name,value] of [['Email',item.contact_email||'Not added'],['Company',item.company_name],['Next follow-up',item.next_followup_date?formatDate(item.next_followup_date):'Not planned'],['Status',item.status]]){
      const field=element('div','');field.append(element('dt','',name),element('dd','',value));fields.append(field);
    }
    detail.append(fields);
    const history=element('section','relation-history');history.append(element('h3','','Interaction history'));
    if(item.notes){for(const line of item.notes.split(/\n(?=\[\d{4}-\d{2}-\d{2}\])/)){
      const event=element('div','relation-event');const match=line.match(/^\[(\d{4}-\d{2}-\d{2})\]\s*([\s\S]*)$/);
      if(match)event.append(element('small','',formatDate(match[1])),element('p','',match[2]));else event.append(element('small','','Saved notes'),element('p','',line));history.append(event);
    }}else history.append(element('p','text-sm text-slate-400','No interactions recorded yet.'));
    if(item.last_contact_date)history.append(element('p','text-xs text-slate-400 mt-3','Last contact: '+formatDate(item.last_contact_date)));
    detail.append(history);
    if(!item.read_only){const add=element('button','btn btn-secondary w-full mt-5','Add interaction ＋');add.type='button';add.addEventListener('click',()=>{
      document.getElementById('interaction-form').reset();document.getElementById('interaction-date').value=new Date().toLocaleDateString('en-CA');document.getElementById('interaction-error').classList.add('hidden');document.getElementById('interaction-dialog').showModal();
    });detail.append(add);}
  }
  function render() {
    updateCategoryFilter();
    const visible=filteredApplications();
    if(!visible.some(item=>item.id===selectedId))selectedId=visible[0]?.id??null;
    board.replaceChildren();
    for(const item of visible){
      const row=element('button','relation-row');row.type='button';row.setAttribute('aria-pressed',String(item.id===selectedId));
      row.append(element('span','relation-avatar',initials(item)));
      const text=element('span','relation-copy');text.append(element('strong','',label(item)),element('p','',item.company_name),element('p','','Last contact: '+formatDate(item.last_contact_date)));row.append(text);
      const meta=element('span','relation-meta');meta.append(element('span','relation-status',item.status),element('span','',item.next_followup_date?'Follow-up '+formatDate(item.next_followup_date):'No follow-up planned'));row.append(meta);
      row.addEventListener('click',()=>{selectedId=item.id;render();});board.append(row);
    }
    if(!visible.length)board.append(element('p','relation-empty',applications.length?'No contacts match your search.':'No contacts yet. Add your first contact.'));
    document.getElementById('crm-results').textContent=visible.length+' contacts';
    renderDetails(visible.find(item=>item.id===selectedId));
  }

  async function loadApplications() {
    try {
      const results = await request(applicationsUrl, { headers: {} });
      applications.splice(0, applications.length, ...results);
      clearError();
      render();
    } catch (error) {
      showError(error.message);
    }
  }

  async function saveStatus(applicationId, status) {
    const application = applications.find((item) => item.id === applicationId);
    if (!application || application.read_only || application.status === status) return;
    const previous = application.status;
    application.status = status;
    render();
    try {
      const updated = await request(`${applicationsUrl}/${applicationId}`, {
        method: "PUT",
        body: JSON.stringify({ status }),
      });
      Object.assign(application, updated);
      clearError();
      render();
    } catch (error) {
      application.status = previous;
      showError(error.message);
      render();
    }
  }

  function openEditor(application) {
    form.reset();
    clearError(true);
    document.getElementById("application-form-error").classList.add("hidden");
    const isEditing = Boolean(application);
    document.getElementById("application-dialog-title").textContent = isEditing ? "Edit contact" : "Add contact";
    document.getElementById("application-id").value = isEditing ? application.id : "";
    document.getElementById("company-field").hidden = isEditing;
    const companySelect = document.getElementById("application-company");
    companySelect.disabled = isEditing;
    companySelect.required = !isEditing;
    document.getElementById("application-email").value = application?.contact_email || "";
    document.getElementById("application-last-contact").value = application?.last_contact_date || "";
    document.getElementById("application-followup").value = application?.next_followup_date || "";
    document.getElementById("application-status").value = application?.status || "Draft";
    document.getElementById("application-notes").value = application?.notes || "";
    document.getElementById("save-application-btn").textContent = isEditing ? "Save changes" : "Save contact";
    document.getElementById("delete-application-btn").classList.toggle("hidden", !isEditing);
    dialog.showModal();
  }

  document.getElementById("application-company").addEventListener("change", (event) => {
    const option = event.target.selectedOptions[0];
    if (option.dataset.email) document.getElementById("application-email").value = option.dataset.email;
  });
  document.getElementById("add-application-btn").addEventListener("click", () => openEditor(null));
  document.getElementById("close-application-dialog").addEventListener("click", () => dialog.close());
  document.getElementById("cancel-application-dialog").addEventListener("click", () => dialog.close());
  document.getElementById("delete-application-btn").addEventListener("click", async () => {
    const id = document.getElementById("application-id").value;
    if (!id) return;
    try {
      await request(`${applicationsUrl}/${id}`, { method: "DELETE" });
      dialog.close();
      await loadApplications().then(() => {
    if (window.location.hash === "#add" || new URLSearchParams(window.location.search).get("action") === "add") {
      openEditor(null);
    }
  });
    } catch (error) {
      showError(error.message, true);
    }
  });
  ["crm-search", "crm-status-filter", "crm-category-filter"].forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
    document.getElementById(id).addEventListener("change", render);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError(true);
    const id = document.getElementById("application-id").value;
    const payload = {
      contact_email: document.getElementById("application-email").value,
      last_contact_date: document.getElementById("application-last-contact").value,
      next_followup_date: document.getElementById("application-followup").value,
      status: document.getElementById("application-status").value,
      notes: document.getElementById("application-notes").value,
    };
    if (!id) payload.company_id = document.getElementById("application-company").value;
    const saveButton = document.getElementById("save-application-btn");
    saveButton.disabled = true;
    saveButton.textContent = "Saving...";
    try {
      if (id) {
        await request(`${applicationsUrl}/${id}`, { method: "PUT", body: JSON.stringify(payload) });
      } else {
        await request(applicationsUrl, { method: "POST", body: JSON.stringify(payload) });
      }
      dialog.close();
      await loadApplications();
    } catch (error) {
      showError(error.message, true);
    } finally {
      saveButton.disabled = false;
      saveButton.textContent = id ? "Save changes" : "Save contact";
    }
  });

  document.getElementById('interaction-cancel').addEventListener('click',()=>document.getElementById('interaction-dialog').close());
  document.getElementById('interaction-form').addEventListener('submit',async event=>{
    event.preventDefault();const item=applications.find(item=>item.id===selectedId);if(!item||item.read_only)return;
    const note=document.getElementById('interaction-note').value.trim();const date=document.getElementById('interaction-date').value;
    const error=document.getElementById('interaction-error');
    const notes=((item.notes||'')+'\n['+date+'] '+note).trim();
    if(notes.length>3000){error.textContent='Notes are full. Edit contact notes before adding another interaction.';error.classList.remove('hidden');return;}
    const button=event.target.querySelector('[type=submit]');button.disabled=true;
    try{await request(`${applicationsUrl}/${item.id}`,{method:'PUT',body:JSON.stringify({notes,last_contact_date:date})});document.getElementById('interaction-dialog').close();await loadApplications();}
    catch(exc){error.textContent=exc.message;error.classList.remove('hidden');}finally{button.disabled=false;}
  });
  loadApplications();
})();
