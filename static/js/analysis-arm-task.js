(function () {
  function $(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    const t = String(s == null ? "" : s);
    return t
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function applyAudioTasks() {
    const r = await fetch("/api/analysis/arm-task/apply-audio-tasks", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    return r.json();
  }

  async function loadArmTask() {
    const statusEl = $("arm-task-status");
    const metaEl = $("arm-task-meta");
    const wrap = $("arm-task-matched-wrap");
    const tbody = $("arm-task-matched-body");
    const allBody = $("arm-task-all-blocks-body");
    if (!statusEl) return;

    statusEl.textContent = "Загрузка…";
    if (metaEl) metaEl.innerHTML = "";
    if (wrap) wrap.style.display = "none";
    if (tbody) tbody.innerHTML = "";
    if (allBody) allBody.innerHTML = "";

    let j;
    try {
      const r = await fetch("/api/analysis/arm-task", { credentials: "same-origin" });
      j = await r.json();
    } catch (e) {
      statusEl.textContent = "Ошибка сети: " + (e.message || e);
      return;
    }

    if (!j.ok) {
      statusEl.textContent = j.error || "Ошибка";
      if (metaEl && j.configured_path != null) {
        metaEl.innerHTML =
          '<span class="wp-subtle">Задано:</span> <code class="small">' +
          esc(j.configured_path || "—") +
          "</code>";
      }
      return;
    }

    statusEl.textContent = "Готово. Синхронизирую аудиозадание…";
    const srcLine =
      "<div><strong>Файл:</strong> <code class=\"small\">" +
      esc(j.source_path) +
      "</code>" +
      (j.source_mtime ? " · изменён: " + esc(j.source_mtime) : "") +
      (j.picked_newest_from_dir ? " · <span class=\"wp-subtle\">взят самый новый XML в каталоге</span>" : "") +
      "</div>";

    const matched = j.matched;
    let matchedHtml = "";
    if (matched && tbody && wrap) {
      const rows = matched.rows || [];
      if (rows.length) {
        wrap.style.display = "";
        tbody.innerHTML = rows
          .map((row) => {
            const badge = row.in_catalog
              ? '<span class="badge text-bg-success">да</span>'
              : '<span class="badge text-bg-secondary">нет</span>';
            return (
              "<tr><td class=\"wp-mono\">" +
              esc(row.freq_mhz) +
              "</td><td>" +
              esc(row.comment) +
              "</td><td>" +
              badge +
              "</td></tr>"
            );
          })
          .join("");
      } else {
        wrap.style.display = "";
        tbody.innerHTML =
          '<tr><td colspan="3" class="text-muted">В блоке нет строк TaskBlockItem</td></tr>';
      }
      matchedHtml =
        '<div class="mt-2 wp-subtle">' +
        esc(matched.name || "—") +
        (matched.creation_time ? " · " + esc(matched.creation_time) : "") +
        (matched.plugin_title ? " · " + esc(matched.plugin_title) : "") +
        " · каналов: " +
        esc(String(matched.channel_count || 0)) +
        " · совпадений со справочником позиции: " +
        esc(String(j.matched_freq_intersections || 0)) +
        "</div>";
    } else if (wrap) {
      wrap.style.display = "none";
    }

    if (metaEl) metaEl.innerHTML = srcLine + matchedHtml;

    if (allBody && Array.isArray(j.blocks)) {
      const parts = j.blocks.map((b) => {
        const isMatch =
          j.matched_block_index != null && Number(b.index) === Number(j.matched_block_index);
        const title =
          (isMatch ? '<span class="badge text-bg-primary me-1">задание поста</span>' : "") +
          esc(b.name || "—") +
          (b.creation_time ? " · " + esc(b.creation_time) : "") +
          " · строк: " +
          String((b.rows && b.rows.length) || 0);
        const rows = (b.rows || [])
          .map(
            (row) =>
              "<tr><td class=\"wp-mono\">" +
              esc(row.freq_mhz) +
              "</td><td>" +
              esc(row.comment) +
              "</td></tr>"
          )
          .join("");
        return (
          '<div class="mb-3 border rounded p-2">' +
          "<div class=\"fw-semibold small mb-1\">" +
          title +
          "</div>" +
          '<table class="table table-sm mb-0"><thead><tr><th>МГц</th><th>Комментарий</th></tr></thead><tbody>' +
          rows +
          "</tbody></table></div>"
        );
      });
      allBody.innerHTML = parts.join("") || "<span class=\"wp-subtle\">Нет блоков</span>";
    }

    try {
      const synced = await applyAudioTasks();
      if (synced.ok) {
        statusEl.textContent =
          "Готово. Аудиозадание обновлено: активных частот " +
          String(synced.active_count || 0) +
          ".";
      } else {
        statusEl.textContent =
          "XML загружен, но аудиозадание не обновлено: " + (synced.error || "ошибка");
      }
    } catch (e) {
      statusEl.textContent =
        "XML загружен, но аудиозадание не обновлено: " + (e.message || e);
    }
  }

  async function loadSettings() {
    const inp = $("arm-task-path-input");
    const msg = $("arm-task-path-msg");
    if (!inp || !msg) return;
    msg.textContent = "…";
    try {
      const r = await fetch("/api/analysis/arm-task/settings", { credentials: "same-origin" });
      const j = await r.json();
      if (!j.ok) {
        msg.textContent = j.error || "Ошибка";
        return;
      }
      inp.value = j.effective_path || "";
      msg.textContent = j.from_db
        ? "Источник: сохранённый путь в БД"
        : j.from_env
          ? "Источник: WEB_PORTAL_ARM_TASK_XML_DIR"
          : "Источник: hub_config.json или не задан";
    } catch (e) {
      msg.textContent = String(e.message || e);
    }
  }

  async function savePath() {
    const inp = $("arm-task-path-input");
    const msg = $("arm-task-path-msg");
    if (!inp || !msg) return;
    const dir = String(inp.value || "").trim();
    msg.textContent = "Сохранение…";
    try {
      const r = await fetch("/api/analysis/arm-task/settings", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dir }),
      });
      const j = await r.json();
      if (!j.ok) {
        msg.textContent = j.error || "Ошибка";
        return;
      }
      msg.textContent = j.cleared ? "Сброшено" : "Сохранено";
      await loadArmTask();
    } catch (e) {
      msg.textContent = String(e.message || e);
    }
  }

  async function clearPath() {
    const inp = $("arm-task-path-input");
    const msg = $("arm-task-path-msg");
    if (!inp || !msg) return;
    inp.value = "";
    msg.textContent = "Сброс…";
    try {
      const r = await fetch("/api/analysis/arm-task/settings", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dir: "" }),
      });
      const j = await r.json();
      msg.textContent = j.ok ? "Сброшено" : j.error || "Ошибка";
      await loadSettings();
      await loadArmTask();
    } catch (e) {
      msg.textContent = String(e.message || e);
    }
  }

  function bind() {
    const refresh = $("arm-task-refresh");
    if (refresh) refresh.addEventListener("click", () => loadArmTask().catch(() => {}));
    const save = $("arm-task-path-save");
    if (save) save.addEventListener("click", () => savePath().catch(() => {}));
    const clr = $("arm-task-path-clear");
    if (clr) clr.addEventListener("click", () => clearPath().catch(() => {}));
  }

  window.ArmTaskView = {
    activate() {
      loadArmTask().catch(() => {});
      if ($("arm-task-path-input")) loadSettings().catch(() => {});
    },
  };

  document.addEventListener("DOMContentLoaded", () => {
    bind();
  });
})();
