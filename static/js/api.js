/**
 * Общие запросы к API (используются на всех страницах).
 */
const API_ETAG_CACHE = new Map();

function apiEtagCacheClear(urlPrefix) {
  if (!urlPrefix) {
    API_ETAG_CACHE.clear();
    return;
  }
  const prefix = String(urlPrefix);
  for (const key of Array.from(API_ETAG_CACHE.keys())) {
    if (String(key).startsWith(prefix)) API_ETAG_CACHE.delete(key);
  }
}

async function apiGet(url, options) {
  const cached = API_ETAG_CACHE.get(url);
  const headers = { ...((options && options.headers) || {}) };
  if (cached && cached.etag) headers["If-None-Match"] = cached.etag;
  const opts = { method: "GET", cache: "no-cache", ...options, headers };
  const res = await fetch(url, opts);
  if (res.status === 304 && cached) return cached.data;
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  const etag = res.headers.get("ETag");
  if (etag) API_ETAG_CACHE.set(url, { etag, data });
  return data;
}

async function apiGetWithTimeout(url, timeoutMs) {
  timeoutMs = Number(timeoutMs) || 12000;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const cached = API_ETAG_CACHE.get(url);
    const headers = cached && cached.etag ? { "If-None-Match": cached.etag } : {};
    const res = await fetch(url, { method: "GET", cache: "no-cache", headers, signal: controller.signal });
    if (res.status === 304 && cached) return cached.data;
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
    const etag = res.headers.get("ETag");
    if (etag) API_ETAG_CACHE.set(url, { etag, data });
    return data;
  } catch (e) {
    const msg = (e && e.message) ? String(e.message) : "";
    if (e && (e.name === "AbortError" || /abort|timeout/i.test(msg)))
      throw new Error("Таймаут запроса (" + Math.round(timeoutMs / 1000) + " сек)");
    throw e;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function sleepExportJob(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitExportJob(jobId, statusSetter) {
  const id = Number(jobId || 0);
  if (!id) throw new Error("Сервер не вернул job_id");
  const maxWaitMs = Number(
    window.WEB_PORTAL_EXPORT_MAX_WAIT_MS || 6 * 60 * 60 * 1000
  );
  const pollTimeoutMs = Number(
    window.WEB_PORTAL_EXPORT_POLL_TIMEOUT_MS || 300000
  );
  const startedAt = Date.now();
  let delay = 1000;
  for (;;) {
    if (Date.now() - startedAt > maxWaitMs) {
      throw new Error(
        "Экспорт не завершился за допустимое время. Попробуйте сузить период или повторите позже."
      );
    }
    if (document.hidden) {
      await sleepExportJob(Math.max(delay, 10000));
      continue;
    }
    const data = await apiGetWithTimeout(
      `/api/export-jobs/${encodeURIComponent(id)}`,
      pollTimeoutMs
    );
    const job = data.job || {};
    const status = String(job.status || "").toLowerCase();
    if (status === "completed") return job;
    if (status === "failed" || status === "cancelled") {
      throw new Error(job.error_text || "Экспорт завершился с ошибкой");
    }
    if (typeof statusSetter === "function") {
      statusSetter(
        status === "pending"
          ? "Экспорт в очереди…"
          : "Формирование Word (подождите)…"
      );
    }
    await sleepExportJob(delay);
    delay = Math.min(4000, Math.round(delay * 1.25));
  }
}

async function queueExportJob(postUrl, body, statusSetter) {
  const postTimeoutMs = Number(
    window.WEB_PORTAL_EXPORT_POST_TIMEOUT_MS || 180000
  );
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), postTimeoutMs);
  let data;
  try {
    const res = await fetch(postUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      signal: controller.signal,
    });
    data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || data.message || `HTTP ${res.status}`);
    }
  } catch (e) {
    const msg = (e && e.message) ? String(e.message) : "";
    if (e && (e.name === "AbortError" || /abort|timeout/i.test(msg))) {
      throw new Error(
        "Сервер не успел принять задачу экспорта (очередь занята). Подождите и повторите."
      );
    }
    throw e;
  } finally {
    clearTimeout(timeoutId);
  }
  const jobId = Number(data.job_id || 0);
  if (!jobId) throw new Error("Сервер не вернул job_id");
  if (typeof statusSetter === "function") {
    statusSetter("Экспорт поставлен в очередь…");
  }
  await waitExportJob(jobId, statusSetter);
  return jobId;
}

async function downloadExportJob(jobId, filename) {
  const response = await fetch(`/api/export-jobs/${encodeURIComponent(jobId)}/download`);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "export";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
}
