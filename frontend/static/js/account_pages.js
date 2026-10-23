(() => {
  const profileDialog = document.getElementById("profile-editor");
  if (profileDialog) {
    const profileForm = document.getElementById('profile-details-form');
    document.getElementById('edit-profile-button')?.addEventListener('click', () => {
      profileForm?.querySelector('[name="full_name"]')?.focus();
    });
    const savedSkills = document.getElementById('saved-target-skills');
    profileForm?.querySelectorAll('[name="target_skills_selected"], input[name="target_skills"]:not([type="hidden"])').forEach(field => {
      field.addEventListener('input', () => { if (savedSkills) savedSkills.disabled = true; });
    });
    profileForm?.addEventListener('reset', () => {
      if (savedSkills) savedSkills.disabled = false;
    });
    profileForm?.addEventListener('invalid', event => {
      const details = event.target.closest('details');
      if (details) details.open = true;
    }, true);
    profileForm?.addEventListener('submit', () => {
      const saveButton = document.getElementById('save-profile-button');
      if (saveButton) { saveButton.disabled = true; saveButton.textContent = 'Saving…'; }
    });
  }

  const table = document.getElementById("applications-table");
  if (!table) return;

  const search = document.getElementById("application-search");
  const statusFilter = document.getElementById("application-status-filter");
  const sort = document.getElementById("application-sort");
  const count = document.getElementById("application-count");
  const noResults = document.getElementById("applications-no-results");
  const body = table.tBodies[0];
  const rows = [...body.rows];

  function compareRows(left, right) {
    switch (sort.value) {
      case "updated-desc":
        return right.dataset.updated.localeCompare(left.dataset.updated);
      case "company-asc":
        return left.dataset.company.localeCompare(right.dataset.company);
      case "status-asc":
        return left.dataset.status.localeCompare(right.dataset.status);
      case "score-desc":
        return Number(right.dataset.score) - Number(left.dataset.score);
      case "applied-desc":
      default:
        return right.dataset.applied.localeCompare(left.dataset.applied);
    }
  }

  function updateApplications() {
    const query = search.value.trim().toLocaleLowerCase();
    const status = statusFilter.value;
    const ordered = [...rows].sort(compareRows);
    const visible = ordered.filter((row) => {
      const matchesQuery = !query
        || `${row.dataset.company} ${row.dataset.position} ${row.dataset.status}`.includes(query);
      return matchesQuery && (status === "all" || row.dataset.status === status);
    });

    ordered.forEach((row) => {
      row.hidden = !visible.includes(row);
      body.append(row);
    });
    count.textContent = `${visible.length} ${visible.length === 1 ? "application" : "applications"}`;
    noResults.classList.toggle("hidden", visible.length > 0);
  }

  search.addEventListener("input", updateApplications);
  statusFilter.addEventListener("change", updateApplications);
  sort.addEventListener("change", updateApplications);
  updateApplications();
})();
