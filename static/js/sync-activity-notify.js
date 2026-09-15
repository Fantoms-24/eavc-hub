/* Red markers for new HUB data. Loaded on every authenticated server page. */
(function () {
  const current = document.body?.dataset?.activitySection || "";
  const pollMs = 5000;
  const marker = (section) => document.querySelector(`[data-activity-marker="${section}"]`);
  function apply(sections) {
    ["intercepts", "aviation"].forEach((section) => {
      const el = marker(section); if (!el) return;
      const item = sections?.[section];
      const units = Array.isArray(item?.units) ? item.units.filter(Boolean) : [];
      const active = Boolean(item?.count);
      el.hidden = !active;
      el.title = active ? `Новые данные: ${units.join(", ") || "подразделение не указано"}` : "";
      el.setAttribute("aria-label", el.title || "");
    });
  }
  async function poll() {
    try {
      const response = await fetch("/api/activity-notifications", {cache: "no-store", credentials: "same-origin"});
      const data = await response.json(); if (data?.ok) apply(data.sections || {});
    } catch (_error) { /* temporary network failure */ }
  }
  async function markCurrentRead() {
    if (!current) return;
    try { await fetch(`/api/activity-notifications/${encodeURIComponent(current)}/read`, {method: "POST", credentials: "same-origin"}); }
    catch (_error) { /* retry on next page opening */ }
  }
  if (current) markCurrentRead().finally(poll); else poll();
  setInterval(poll, pollMs); addEventListener("focus", poll);
})();
