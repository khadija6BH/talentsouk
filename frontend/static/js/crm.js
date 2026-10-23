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

  function updateCounters() {
    const counts = {
      target: applications.filter((item) => item.status === "Draft").length,
      wishlist: applications.filter((item) => item.status === "Wishlist").length,
      applied: applications.filter((item) => ["Sent", "Replied", "Interview", "Accepted", "Rejected"].includes(item.status)).length,
      replies: applications.filter((item) => ["Replied", "Interview", "Accepted"].includes(item.status)).length,
      interviews: applications.filter((item) => ["Interview", "Accepted"].includes(item.status)).length,
      offers: applications.filter((item) => item.status === "Accepted").length,
    };
    Object.entries(counts).forEach(([name, count]) => {
      document.getElementById(`count-${name}`).textContent = count;
    });
  }

  function updateCategoryFilter() {
    const select = document.getElementById("crm-category-filter");
    const selected = select.value;
    const categories = [...new Set(applications.map((item) => item.category))].sort();
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
        && (category === "all" || item.category === category);
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

  function renderCard(application) {
    const card = element("article", "crm-card");
    card.draggable = !application.read_only;
    card.dataset.id = application.id;
    card.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", String(application.id));
      event.dataTransfer.effectAllowed = "move";
      card.classList.add("is-dragging");
    });
    card.addEventListener("dragend", () => card.classList.remove("is-dragging"));

    const top = element("div", "crm-card-top");
    const company = companyOptions[String(application.company_id)] || {category:application.category,url:""};
    const companyLink = element(company.url ? "a" : "span", "crm-company-link", application.company_name);
    if (company.url) companyLink.href = company.url;
    top.append(companyLink);
    if (company.category) top.append(element("span", "crm-category", company.category));
    card.append(top);

    const details = element("div", "crm-details");
    addDetail(details, "Contact", application.contact_email, application.contact_email ? `mailto:${application.contact_email}` : "");
    addDetail(details, "Date added", formatDate(application.created_at));
    addDetail(details, "Last contact", formatDate(application.last_contact_date));
    card.append(details);

    const note = element("p", "crm-note", application.notes || "No notes yet.");
    card.append(note);

    if(application.read_only){
      if(application.position)card.append(element('p','crm-note',application.position));
      card.append(element('p','crm-note','Company removed from catalog. Application history is preserved.'));
      const history=element('a','crm-edit-button','View application history');history.href='/crm/applications';card.append(history);
      return card;
    }
    const statusLabel = element("label", "crm-card-status", "Current status");
    const statusSelect = element("select", "crm-status-select");
    statusSelect.setAttribute("aria-label", `Current status for ${application.company_name}`);
    statuses.forEach((status) => statusSelect.add(new Option(status, status)));
    statusSelect.value = application.status;
    statusSelect.addEventListener("change", () => saveStatus(application.id, statusSelect.value));
    statusLabel.append(statusSelect);
    card.append(statusLabel);

    const editButton = element("button", "crm-edit-button", "Edit details");
    editButton.type = "button";
    editButton.addEventListener("click", () => openEditor(application));
    card.append(editButton);
    return card;
  }

  function render() {
    updateCounters();
    updateCategoryFilter();
    const visible = filteredApplications();
    const statusFilter = document.getElementById("crm-status-filter").value;
    const categoryFilter = document.getElementById("crm-category-filter").value;
    const query = document.getElementById("crm-search").value.trim();
    const laneStatuses = statusFilter === "all" ? statuses : [statusFilter];

    board.replaceChildren();
    laneStatuses.forEach((status) => {
      const lane = element("section", "crm-lane");
      lane.dataset.status = status;
      lane.setAttribute("aria-label", `${status} applications`);
      lane.addEventListener("dragover", (event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        lane.classList.add("is-over");
      });
      lane.addEventListener("dragleave", (event) => {
        if (!lane.contains(event.relatedTarget)) lane.classList.remove("is-over");
      });
      lane.addEventListener("drop", (event) => {
        event.preventDefault();
        lane.classList.remove("is-over");
        const applicationId = Number(event.dataTransfer.getData("text/plain"));
        saveStatus(applicationId, status);
      });

      const laneHeader = element("header", "crm-lane-header");
      laneHeader.append(element("h2", "crm-lane-title", status));
      const count = visible.filter((item) => item.status === status).length;
      laneHeader.append(element("span", "crm-lane-count", String(count)));
      lane.append(laneHeader);

      const laneCards = visible.filter((item) => item.status === status);
      if (!laneCards.length) {
        lane.append(element("p", "crm-lane-empty", "No applications here"));
      } else {
        laneCards.forEach((application) => lane.append(renderCard(application)));
      }
      board.append(lane);
    });

    document.getElementById("crm-results").textContent =
      `${visible.length} ${visible.length === 1 ? "application" : "applications"}`;
    if (applications.length && !visible.length && (query || statusFilter !== "all" || categoryFilter !== "all")) {
      board.append(element("p", "crm-no-results", "No applications match these filters."));
    } else if (!applications.length) {
      board.append(element("p", "crm-no-results", "No applications yet. Add a company to start your pipeline."));
    }
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
    document.getElementById("application-dialog-title").textContent = isEditing ? "Edit application" : "Add application";
    document.getElementById("application-id").value = isEditing ? application.id : "";
    document.getElementById("company-field").hidden = isEditing;
    const companySelect = document.getElementById("application-company");
    companySelect.disabled = isEditing;
    companySelect.required = !isEditing;
    document.getElementById("application-email").value = application?.contact_email || "";
    document.getElementById("application-last-contact").value = application?.last_contact_date || "";
    document.getElementById("application-status").value = application?.status || "Draft";
    document.getElementById("application-notes").value = application?.notes || "";
    document.getElementById("save-application-btn").textContent = isEditing ? "Save changes" : "Save application";
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
      saveButton.textContent = id ? "Save changes" : "Save application";
    }
  });

  loadApplications();
})();
