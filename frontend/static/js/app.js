/*
  TalentSouk — global vanilla JS.
  Keep this file framework-free. Add new small behaviors here as
  new components are introduced (modals, dropdowns, etc.).
*/

document.addEventListener("DOMContentLoaded", function () {
  initNotifications();
  initSidebarToggle();
  initProfileMenu();
  initGlobalSearch();
  initLanguageSelector();
  initUpgradePlan();
});

function initLanguageSelector() {
  const selector = document.getElementById("language-selector");
  if (!selector) return;
  selector.addEventListener("change", async () => {
    selector.disabled = true;
    try {
      const response = await fetch("/api/settings/language", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ language: selector.value }),
      });
      if (!response.ok) throw new Error("Language could not be saved.");
      window.setAppLanguage(selector.value);
      selector.disabled = false;
    } catch (error) {
      selector.disabled = false;
      window.alert(window.translateText ? window.translateText(error.message) : error.message);
    }
  });
}

/**
 * Mobile sidebar: toggled open/closed via the hamburger button in the
 * topbar. Uses a backdrop overlay to close on outside click.
 */
function initSidebarToggle() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  const openBtn = document.getElementById('sidebar-open-btn');
  const closeBtn = document.getElementById('sidebar-close-btn');
  const content = document.getElementById('app-content');
  if (!sidebar || !backdrop || !openBtn) return;
  let opened = false;
  let oldOverflow = '';
  function closeSidebar() {
    if (!opened) return;
    opened = false;
    sidebar.classList.add('sidebar-hidden');
    sidebar.setAttribute('aria-hidden', 'true');
    sidebar.inert = true;
    backdrop.classList.add('hidden', 'opacity-0');
    openBtn.setAttribute('aria-expanded', 'false');
    if (content) content.inert = false;
    document.body.style.overflow = oldOverflow;
    openBtn.focus();
  }
  openBtn.addEventListener('click', () => {
    if (document.body.classList.contains('dashboard-editorial') && matchMedia('(min-width:1200px)').matches) return;
    if (opened) { closeSidebar(); return; }
    opened = true;
    oldOverflow = document.body.style.overflow;
    sidebar.inert = false;
    sidebar.setAttribute('aria-hidden', 'false');
    sidebar.classList.remove('sidebar-hidden');
    backdrop.classList.remove('hidden', 'opacity-0');
    openBtn.setAttribute('aria-expanded', 'true');
    if (content) content.inert = true;
    document.body.style.overflow = 'hidden';
    closeBtn?.focus();
  });
  closeBtn?.addEventListener('click', closeSidebar);
  backdrop.addEventListener('click', closeSidebar);
  sidebar.querySelectorAll('nav a').forEach(link => link.addEventListener('click', closeSidebar));
  document.addEventListener('keydown', event => {
    if (!opened) return;
    if (event.key === 'Escape') { event.preventDefault(); closeSidebar(); return; }
    if (event.key !== 'Tab') return;
    const elements = [...sidebar.querySelectorAll('a[href],button:not([disabled]),select,input')].filter(el => el.getClientRects().length);
    const first = elements[0], last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  });
}

function initNotifications() {
  const trigger = document.getElementById("notification-trigger"), menu = document.getElementById("notification-menu"), center = document.getElementById("notification-center");
  const list = document.getElementById("notification-list"), badge = document.getElementById("notification-badge");
  if (!trigger || !menu || !list) return;
  const error = document.getElementById("notification-error");
  let signature = "", pending = false;
  async function refresh() {
    if (document.hidden || pending) return;
    pending = true;
    try {
      const response = await fetch("/api/notifications", {cache:"no-store",headers:{Accept:"application/json"}});
      if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) {
        throw new Error(response.status === 403 ? "Complete your profile or verify your email to load notifications." : "Could not load notifications. Please try again.");
      }
      error?.classList.add("hidden");
      const data = await response.json();
      badge.textContent = data.unread; badge.classList.toggle("hidden", !data.unread);
      const next = JSON.stringify(data.items); if (next === signature) return; signature = next;
      list.replaceChildren();
      for (const item of data.items) {
        const link = document.createElement("a");
        link.href = item.url?.startsWith("/") && !item.url.startsWith("//") && !item.url.includes("\\") ? item.url : "#";
        link.className = "notification-item block p-3 rounded-lg hover:bg-slate-50" + (item.is_read ? " opacity-60" : ""); link.dataset.id = item.id;
        const row = document.createElement("div"); row.className = "flex justify-between gap-2";
        const title = document.createElement("span"); title.className = "text-sm font-semibold text-slate-700"; title.textContent = item.title;
        const time = document.createElement("time"); time.className = "text-[10px] text-slate-400"; time.textContent = String(item.created_at || "").slice(0,16);
        const message = document.createElement("p"); message.className = "text-xs text-slate-500 mt-1"; message.textContent = item.message;
        row.append(title,time); link.append(row,message); list.append(link);
      }
      if (!data.items.length) { const empty = document.createElement("p"); empty.className="p-5 text-center text-sm text-slate-400"; empty.textContent="No matching offers yet. Check your target position and skills in My profile. New matches appear here automatically."; list.append(empty); }
    } catch (failure) {
      if (error) { error.textContent = failure.message; error.classList.remove("hidden"); }
    }
    finally { pending = false; }
  }
  trigger.addEventListener("click", e => { e.stopPropagation(); menu.classList.toggle("hidden"); trigger.setAttribute("aria-expanded", String(!menu.classList.contains("hidden"))); refresh(); });
  center.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", () => { menu.classList.add("hidden"); trigger.setAttribute("aria-expanded","false"); });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !menu.classList.contains("hidden")) {
      menu.classList.add("hidden"); trigger.setAttribute("aria-expanded", "false"); trigger.focus();
    }
  });
  menu.addEventListener("click", async e => {
    const action = e.target.closest(".notification-action"), item = e.target.closest(".notification-item");
    if (action) {
      action.disabled = true;
      try {
        const response = await fetch(`/api/notifications/${action.dataset.action}`, {method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
        if (!response.ok) throw new Error("Could not update notifications. Please try again.");
        error?.classList.add("hidden"); await refresh();
      } catch (failure) {
        if (error) { error.textContent = failure.message; error.classList.remove("hidden"); }
      } finally { action.disabled = false; }
    }
    else if (item) fetch("/api/notifications/read", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:item.dataset.id}),keepalive:true});
  });
  setInterval(refresh,60000); document.addEventListener("visibilitychange",refresh); refresh();
}

/**
 * Profile menu dropdown in the topbar.
 */
function initProfileMenu() {
  const trigger = document.getElementById("profile-menu-trigger");
  const menu = document.getElementById("profile-menu");

  if (!trigger || !menu) return;

  trigger.addEventListener("click", function (e) {
    e.stopPropagation();
    menu.classList.toggle("hidden");
  });

  document.addEventListener("click", function () {
    menu.classList.add("hidden");
  });
}

function initGlobalSearch() {
  const wrapper = document.getElementById("global-search");
  const input = document.getElementById("global-search-input");
  const results = document.getElementById("global-search-results");
  if (!wrapper || !input || !results) return;

  let debounceTimer;
  let requestSequence = 0;

  function closeResults() {
    results.classList.add("hidden");
    input.setAttribute("aria-expanded", "false");
  }

  function showMessage(message) {
    results.replaceChildren();
    const item = document.createElement("p");
    item.className = "px-3 py-2 text-sm text-slate-500";
    item.textContent = message;
    results.appendChild(item);
    results.classList.remove("hidden");
    input.setAttribute("aria-expanded", "true");
  }

  function renderResults(items) {
    results.replaceChildren();
    if (!items.length) {
      showMessage("No matching results.");
      return;
    }

    items.forEach((item) => {
      const link = document.createElement("a");
      link.href = item.url;
      link.className = "block rounded-lg px-3 py-2.5 hover:bg-blue-50 focus:bg-blue-50 focus:outline-none";

      const heading = document.createElement("div");
      heading.className = "flex items-center justify-between gap-3";
      const name = document.createElement("span");
      name.className = "truncate text-sm font-medium text-slate-800";
      name.textContent = item.name;
      const type = document.createElement("span");
      type.className = "shrink-0 rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700";
      type.textContent = item.type;
      heading.append(name, type);
      link.appendChild(heading);

      const metadata = [item.location, item.status].filter(Boolean).join(" · ");
      if (metadata) {
        const detail = document.createElement("span");
        detail.className = "mt-1 block truncate text-xs text-slate-500";
        detail.textContent = metadata;
        link.appendChild(detail);
      }
      results.appendChild(link);
    });

    results.classList.remove("hidden");
    input.setAttribute("aria-expanded", "true");
  }

  input.addEventListener("input", function () {
    clearTimeout(debounceTimer);
    const query = input.value.trim();
    const sequence = ++requestSequence;
    if (query.length < 2) {
      closeResults();
      return;
    }

    showMessage("Searching…");
    debounceTimer = setTimeout(async function () {
      try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
        if (!response.ok) throw new Error("Search request failed");
        const payload = await response.json();
        if (sequence === requestSequence && input.value.trim() === query) {
          renderResults(payload.results || []);
        }
      } catch (error) {
        if (sequence === requestSequence) showMessage("Search is temporarily unavailable.");
      }
    }, 180);
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeResults();
  });
  document.addEventListener("click", function (event) {
    if (!wrapper.contains(event.target)) closeResults();
  });
}

function initUpgradePlan() {
  const upgradeBtn = document.getElementById("upgrade-plan-btn");
  if (!upgradeBtn) return;
  upgradeBtn.addEventListener("click", function () {
    window.alert(
      "All TalentSouk Pro features (unlimited CV optimizations, AI cover letters, and local match heuristics) are currently active and unlocked for your account!"
    );
  });
}
