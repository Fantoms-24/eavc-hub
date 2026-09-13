// Chat functionality
let chatModal = null;
let chatMessagesInterval = null;
let chatMessagesInflight = false;
let chatNotifyInflight = false;
let chatLastMessageId = null;
let chatLastMessageIdByChannel = {};
let chatFileId = null;
let chatUnreadCount = 0;
let chatLastCheckedMessageId = null;
let chatChannels = [];
let currentChatChannel = null;
let chatNotifyInterval = null;
let chatSendInflight = false;
let chatCurrentUsername = "";

function chatMessageClasses(msg) {
  const isAiMessage = (msg.callsign || msg.username || "") === "EAVC Manager";
  const isOwn =
    !isAiMessage && chatCurrentUsername && String(msg.username || "") === chatCurrentUsername;
  const classes = ["chat-message"];
  if (isAiMessage) classes.push("chat-message-ai");
  if (isOwn) classes.push("chat-message-own");
  return classes.join(" ");
}

function buildChatMessageHtml(msg) {
  const isAiMessage = (msg.callsign || msg.username || "") === "EAVC Manager";
  const fileHtml = msg.file
    ? `
      <a href="/api/chat/files/${msg.file.id}" class="chat-message-file" target="_blank">
        <i class="bi bi-file-earmark"></i>
        <span>${escapeHtml(msg.file.original_filename || "Файл")}</span>
        ${
          msg.file.file_size
            ? `<span class="text-muted small ms-1">(${formatFileSize(msg.file.file_size)})</span>`
            : ""
        }
      </a>
    `
    : "";

  return `
    <div class="${chatMessageClasses(msg)}" data-message-id="${msg.id}">
      <div class="d-flex align-items-start gap-2">
        <div class="flex-shrink-0">
          <div class="chat-message-avatar">
            ${escapeHtml((msg.callsign || msg.username || "U")[0].toUpperCase())}
          </div>
        </div>
        <div class="flex-grow-1 min-w-0">
          <div class="chat-message-bubble">
            <div class="chat-message-info">
              <span class="chat-message-author">${escapeHtml(chatDisplayName(msg.callsign || msg.username))}</span>
              <span class="chat-message-time">${formatDate(msg.created_at)}</span>
            </div>
            ${
              msg.message_text
                ? `<div class="chat-message-text">${formatChatMessageText(msg.message_text)}</div>`
                : ""
            }
            ${fileHtml}
          </div>
          ${isAiMessage ? buildAiFeedbackBar(msg) : ""}
        </div>
      </div>
    </div>
  `;
}

function chatScrollBehavior() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

function scrollChatToBottom(forceInstant) {
  const container = $("chat-messages-container");
  if (!container) return;
  container.scrollTo({
    top: container.scrollHeight,
    behavior: forceInstant ? "auto" : chatScrollBehavior(),
  });
  updateChatScrollBottomBtn();
}

function updateChatScrollBottomBtn() {
  const container = $("chat-messages-container");
  const btn = $("chat-scroll-bottom");
  if (!container || !btn) return;
  const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 88;
  btn.hidden = atBottom;
}

function setChatSidebarOpen(open) {
  const modal = $("chatModal");
  const toggle = $("chat-sidebar-toggle");
  const backdrop = $("chat-sidebar-backdrop");
  const main = modal?.querySelector(".chat-main");
  if (!modal) return;
  modal.classList.toggle("chat-sidebar-open", !!open);
  if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
  if (backdrop) backdrop.hidden = !open;
  if (main) {
    if (open && window.matchMedia("(max-width: 991.98px)").matches) main.setAttribute("inert", "");
    else main.removeAttribute("inert");
  }
}

function initChatModernUi() {
  const modal = $("chatModal");
  if (!modal) return;
  chatCurrentUsername = String(modal.dataset.chatUser || "").trim();

  const toggle = $("chat-sidebar-toggle");
  const backdrop = $("chat-sidebar-backdrop");
  const scrollBtn = $("chat-scroll-bottom");
  const container = $("chat-messages-container");

  if (toggle) {
    toggle.addEventListener("click", () => {
      setChatSidebarOpen(!modal.classList.contains("chat-sidebar-open"));
    });
  }
  if (backdrop) {
    backdrop.addEventListener("click", () => setChatSidebarOpen(false));
  }
  if (scrollBtn) {
    scrollBtn.addEventListener("click", () => scrollChatToBottom(false));
  }
  if (container) {
    container.addEventListener("scroll", updateChatScrollBottomBtn, { passive: true });
  }

  const clearBtn = $("chat-clear-history-btn");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => clearChatHistory());
  }

  modal.addEventListener("hidden.bs.modal", () => setChatSidebarOpen(false));
  window.addEventListener("resize", () => {
    if (window.matchMedia("(min-width: 992px)").matches) setChatSidebarOpen(false);
  });
}

function $(id) {
  return document.getElementById(id);
}

async function apiGet(url) {
  const res = await fetch(url, { method: "GET" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
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

function formatDate(dateStr) {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr);
    return d.toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return dateStr;
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

function renderInlineChatMarkdown(text) {
  return String(text || "")
    .replace(/\\([*_`])/g, "$1")
    .replace(/\*\*([\s\S]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__([\s\S]+?)__/g, "<strong>$1</strong>")
    .replace(/`([^`]+?)`/g, "<code>$1</code>");
}

function formatChatMessageText(text) {
  const source = String(text || "");
  const urlPlaceholders = [];
  let escaped = escapeHtml(source);
  escaped = escaped.replace(/\/intercepts\?[^\s<]+/g, (url) => {
    const idx = urlPlaceholders.length;
    const href = url.replace(/&amp;/g, "&");
    urlPlaceholders.push(
      `<a class="chat-open-blank-link" href="${href}" target="_blank" rel="noopener"><i class="bi bi-box-arrow-up-right me-1"></i>Открыть бланк</a>`
    );
    return `@@CHAT_URL_${idx}@@`;
  });
  escaped = escaped
    .replace(/^####\s+(.+)$/gm, (_m, title) => `<div class="chat-md-heading chat-md-heading-4">${renderInlineChatMarkdown(title)}</div>`)
    .replace(/^###\s+(.+)$/gm, (_m, title) => `<div class="chat-md-heading chat-md-heading-3">${renderInlineChatMarkdown(title)}</div>`)
    .replace(/^##\s+(.+)$/gm, (_m, title) => `<div class="chat-md-heading chat-md-heading-2">${renderInlineChatMarkdown(title)}</div>`)
    .replace(/^#\s+(.+)$/gm, (_m, title) => `<div class="chat-md-heading chat-md-heading-1">${renderInlineChatMarkdown(title)}</div>`)
    .replace(/^(\s*)(\d+)\.\s+(.+)$/gm, (_m, indent, num, body) => `${indent}<span class="chat-md-number">${num}.</span> ${renderInlineChatMarkdown(body)}`)
    .replace(/^(\s*)-\s+(.+)$/gm, (_m, indent, body) => `${indent}<span class="chat-md-bullet">•</span> ${renderInlineChatMarkdown(body)}`)
    .replace(/^(\s*)\*\s+(.+)$/gm, (_m, indent, body) => `${indent}<span class="chat-md-bullet">•</span> ${renderInlineChatMarkdown(body)}`)
    .replace(/\*\*([\s\S]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__([\s\S]+?)__/g, "<strong>$1</strong>")
    .replace(/`([^`]+?)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
  return escaped.replace(/@@CHAT_URL_(\d+)@@/g, (_m, idx) => urlPlaceholders[Number(idx)] || "");
}

function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + " " + sizes[i];
}

function isAiChannel(channel) {
  if (!channel) return false;
  if (String(channel.name || "") === "ai_assistant") return true;
  const id = channel.id;
  if (id == null || !Array.isArray(chatChannels) || !chatChannels.length) return false;
  const c = chatChannels.find((x) => String(x.id) === String(id));
  return c && String(c.name || "") === "ai_assistant";
}

function chatDisplayName(name) {
  const n = String(name || "").trim();
  if (n === "EAVC Manager") return "Менеджер ЕАВС";
  return n || "Пользователь";
}

function buildAiFeedbackBar(msg) {
  if (!isAiChannel(currentChatChannel)) return "";
  const gid = currentChatChannel && currentChatChannel.id;
  if (!gid) return "";
  const isAiMessage = (msg.callsign || msg.username || "") === "EAVC Manager";
  if (!isAiMessage) return "";
  const r = msg.ai_feedback;
  const upOn = r === 1;
  const downOn = r === -1;
  return `
    <div class="chat-ai-feedback" data-group-id="${gid}" data-message-id="${msg.id}" role="group" aria-label="Оценка ответа">
      <span class="chat-ai-feedback-label">Полезен ответ?</span>
      <button type="button" class="btn btn-sm chat-ai-feedback-btn chat-ai-feedback-up${
        upOn ? " active" : ""
      }" data-rating="1" title="Полезен" aria-pressed="${upOn}">
        <i class="bi bi-hand-thumbs-up" aria-hidden="true"></i><span class="chat-ai-feedback-txt">да</span>
      </button>
      <button type="button" class="btn btn-sm chat-ai-feedback-btn chat-ai-feedback-down${
        downOn ? " active" : ""
      }" data-rating="-1" title="Не полезен" aria-pressed="${downOn}">
        <i class="bi bi-hand-thumbs-down" aria-hidden="true"></i><span class="chat-ai-feedback-txt">нет</span>
      </button>
    </div>
  `;
}

function updateChatComposerForChannel() {
  const quick = $("chat-ai-quick-prompts");
  const input = $("chat-message-input");
  const title = $("chat-conversation-title");
  const hint = $("chat-conversation-hint");
  const clearBtn = $("chat-clear-history-btn");
  const isAi = isAiChannel(currentChatChannel);
  if (quick) quick.style.display = isAi ? "flex" : "none";
  if (clearBtn) clearBtn.hidden = !currentChatChannel;
  if (input) {
    input.placeholder = isAi
      ? "Спросите менеджера ЕАВС про смену, перехваты, риски или отчёт..."
      : "Введите сообщение...";
  }
  if (title) title.textContent = currentChatChannel?.title || currentChatChannel?.name || "Чат";
  if (hint) {
    hint.textContent = isAi
      ? "Префиксы: поиск: … | только перехваты: … | только бланки: … — сразу полнотекстовый поиск. Enter — отправить. Под ответом: да/нет; при «нет» можно коротко пояснить."
      : "Enter — отправить, Shift+Enter — новая строка";
  }
}

function toggleChatModal() {
  if (!chatModal) {
    const modalEl = $("chatModal");
    if (modalEl && window.bootstrap) {
      chatModal = new bootstrap.Modal(modalEl);
      modalEl.addEventListener("shown.bs.modal", () => {
        chatUnreadCount = 0;
        updateChatBadge();
        stopChatNotifyPolling();
        loadChatChannels(); // загрузка каналов и выбор текущего
        startChatAutoRefresh();
        setTimeout(() => {
          const input = $("chat-message-input");
          if (input) input.focus();
        }, 300);
      });
      modalEl.addEventListener("hidden.bs.modal", () => {
        stopChatAutoRefresh();
        startChatNotifyPolling();
        chatLastCheckedMessageId = chatLastMessageId;
        if (currentChatChannel) {
          try { sessionStorage.setItem("chatLastChannelId", String(currentChatChannel.id)); } catch (_) { }
        }
      });
    }
  }
  if (chatModal) {
    chatModal.toggle();
  }
}

async function loadChatChannels() {
  const listEl = $("chat-channels-list");
  const titleEl = $("chat-current-channel-title");
  if (!listEl) return;
  try {
    const data = await apiGet("/api/chat/channels");
    chatChannels = data.channels || [];
    if (chatChannels.length === 0) {
      listEl.innerHTML = '<li class="list-group-item list-group-item-action text-muted small py-2">Нет доступных каналов</li>';
      if (titleEl) titleEl.textContent = "Нет каналов";
      return;
    }
    listEl.innerHTML = chatChannels.map((ch) => `
      <li class="list-group-item list-group-item-action chat-channel-item py-2" data-channel-id="${ch.id}" data-channel-name="${escapeHtml(ch.name)}" data-channel-title="${escapeHtml(ch.title)}" role="button">
        <i class="bi bi-chat-text me-2 text-muted"></i>${escapeHtml(ch.title)}
      </li>
    `).join("");
    listEl.querySelectorAll(".chat-channel-item").forEach((el) => {
      el.addEventListener("click", () => {
        const id = parseInt(el.getAttribute("data-channel-id"), 10);
        const name = el.getAttribute("data-channel-name");
        const title = el.getAttribute("data-channel-title");
        const ch = chatChannels.find((c) => c.id === id);
        if (ch) switchChatChannel(ch);
      });
    });
    let selected = null;
    try {
      const savedId = sessionStorage.getItem("chatLastChannelId");
      if (savedId) {
        const id = parseInt(savedId, 10);
        selected = chatChannels.find((c) => c.id === id);
      }
    } catch (_) { }
    if (!selected) selected = chatChannels[0];
    switchChatChannel(selected);
  } catch (e) {
    listEl.innerHTML = '<li class="list-group-item list-group-item-action text-danger small py-2">Ошибка загрузки каналов</li>';
    if (titleEl) titleEl.textContent = "Ошибка";
  }
}

function switchChatChannel(channel) {
  if (!channel) return;
  currentChatChannel = channel;
  const titleEl = $("chat-current-channel-title");
  if (titleEl) titleEl.textContent = channel.title || channel.name || "Чат";
  updateChatComposerForChannel();
  if (window.matchMedia("(max-width: 991.98px)").matches) setChatSidebarOpen(false);
  chatLastMessageId = chatLastMessageIdByChannel[channel.id] ?? null;
  $("chat-channels-list")?.querySelectorAll(".chat-channel-item").forEach((el) => {
    const id = parseInt(el.getAttribute("data-channel-id"), 10);
    el.classList.toggle("active", id === channel.id);
  });
  loadChatMessages(false, true);
}

async function clearChatHistory() {
  if (!currentChatChannel) return;
  const channelTitle = currentChatChannel.title || currentChatChannel.name || "чат";
  const isAi = isAiChannel(currentChatChannel);
  const promptText = isAi
    ? `Очистить вашу историю в канале «${channelTitle}»? Ваши сообщения и ответы EAVC Manager будут удалены. Контекст AI тоже сбросится.`
    : `Очистить ваши сообщения в канале «${channelTitle}»?`;
  if (!window.confirm(promptText)) return;

  const clearBtn = $("chat-clear-history-btn");
  if (clearBtn) clearBtn.disabled = true;
  try {
    const data = await apiPost("/api/chat/clear-history", {
      group_id: currentChatChannel.id,
    });
    if (!data.ok) {
      alert(data.error || "Не удалось очистить историю");
      return;
    }
    chatLastMessageId = null;
    chatLastMessageIdByChannel[currentChatChannel.id] = null;
    const container = $("chat-messages-container");
    if (container) {
      container.innerHTML = `
        <div class="text-center text-muted py-5">
          <i class="bi bi-chat-dots fs-1 mb-3 opacity-25"></i>
          <div class="small">История очищена</div>
          <div class="small mt-1">Можно начать новый диалог</div>
        </div>
      `;
    }
  } catch (e) {
    alert("Ошибка при очистке истории: " + (e.message || e));
  } finally {
    if (clearBtn) clearBtn.disabled = false;
  }
}

async function loadChatMessages(showNotification = false, forceReload = false) {
  const container = $("chat-messages-container");
  const isModalVisible = chatModal && chatModal._isShown;
  const groupId = currentChatChannel ? currentChatChannel.id : null;

  try {
    let url = "/api/chat/messages?limit=100";
    if (groupId != null) url += "&group_id=" + encodeURIComponent(groupId);
    if (container && chatLastMessageId && !forceReload) {
      url += "&since_id=" + chatLastMessageId;
    }

    const data = await apiGet(url);
    const messages = data.messages || [];

    // Отображаем сообщения если контейнер существует (чат открыт)
    if (container) {
      // Если нет сообщений вообще
      if (messages.length === 0 && !chatLastMessageId) {
        container.innerHTML = `
          <div class="text-center text-muted py-5">
            <i class="bi bi-chat-dots fs-1 mb-3 opacity-25"></i>
            <div class="small">Пока нет сообщений</div>
            <div class="small mt-1">Начните общение первым!</div>
          </div>
        `;
        return;
      }

      // Инкрементальная загрузка - только новые сообщения
      if (messages.length > 0 && chatLastMessageId && !forceReload) {
        // Фильтруем только действительно новые сообщения (защита от дубликатов)
        const newMessages = messages.filter(msg => {
          // Проверяем, что сообщение еще не отображается
          if (container.querySelector(`[data-message-id="${msg.id}"]`)) {
            return false; // Уже отображается
          }
          return !chatLastMessageId || msg.id > chatLastMessageId;
        });

        if (newMessages.length > 0) {
          // Сохраняем позицию прокрутки перед добавлением
          const wasAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 50;
          const oldScrollHeight = container.scrollHeight;

          // Добавляем только новые сообщения в конец
          newMessages.forEach(msg => {
            container.insertAdjacentHTML("beforeend", buildChatMessageHtml(msg));
          });

          // Обновляем ID последнего сообщения
          const latestId = newMessages[newMessages.length - 1].id;
          if (latestId > chatLastMessageId) {
            chatLastMessageId = latestId;
            if (currentChatChannel) chatLastMessageIdByChannel[currentChatChannel.id] = latestId;
          }

          // Восстанавливаем позицию прокрутки плавно
          requestAnimationFrame(() => {
            if (wasAtBottom) {
              scrollChatToBottom(false);
            } else {
              const newScrollHeight = container.scrollHeight;
              const scrollDiff = newScrollHeight - oldScrollHeight;
              container.scrollTop += scrollDiff;
              updateChatScrollBottomBtn();
            }
          });
        }
        // Если нет новых сообщений - ничего не делаем (не перезагружаем, чат остается на месте)
      } else if (forceReload || !chatLastMessageId) {
        // Полная перезагрузка только при первой загрузке или принудительной
        container.innerHTML = messages.map((msg) => buildChatMessageHtml(msg)).join("");

        requestAnimationFrame(() => {
          scrollChatToBottom(true);
        });
      }

      // Обновляем ID последнего сообщения после отображения (только если были новые)
      if (messages.length > 0 && currentChatChannel) {
        const latestId = messages[messages.length - 1].id;
        if (!chatLastMessageId || latestId > chatLastMessageId) {
          chatLastMessageId = latestId;
          chatLastMessageIdByChannel[currentChatChannel.id] = latestId;
        }
      }

      // Сбрасываем счетчик непрочитанных при открытом чате
      if (isModalVisible) {
        chatUnreadCount = 0;
        updateChatBadge();
        if (chatLastMessageId) {
          chatLastCheckedMessageId = chatLastMessageId;
        }
      }
    }

    // Проверяем новые сообщения если чат закрыт (для уведомлений)
    if (!isModalVisible && messages.length > 0) {
      const latestMessage = messages[messages.length - 1];

      // Обновляем chatLastMessageId для отслеживания
      if (!chatLastMessageId || latestMessage.id > chatLastMessageId) {
        chatLastMessageId = latestMessage.id;
      }

      if (chatLastCheckedMessageId && latestMessage.id > chatLastCheckedMessageId) {
        // Новые сообщения появились, а чат закрыт
        const newMessages = messages.filter(m => m.id > chatLastCheckedMessageId);
        chatUnreadCount += newMessages.length;
        updateChatBadge();

        if (showNotification) {
          showChatNotification();
        }
      }

      // Обновляем ID последнего проверенного сообщения
      if (!chatLastCheckedMessageId || latestMessage.id > chatLastCheckedMessageId) {
        chatLastCheckedMessageId = latestMessage.id;
      }
    }

    // Инициализация при первой загрузке
    if (messages.length > 0 && !chatLastCheckedMessageId && !chatLastMessageId) {
      const firstId = messages[messages.length - 1].id;
      chatLastCheckedMessageId = firstId;
      chatLastMessageId = firstId;
    }
  } catch (e) {
    if (container) {
      container.innerHTML = `<div class="alert alert-danger py-2 small">Ошибка: ${escapeHtml(e.message || String(e))}</div>`;
    }
  }
}

function updateChatBadge() {
  const badge = $("chat-badge");
  if (!badge) return;

  if (chatUnreadCount > 0) {
    badge.textContent = chatUnreadCount > 99 ? "99+" : chatUnreadCount.toString();
    badge.style.display = "flex";
  } else {
    badge.style.display = "none";
  }
}

function showChatNotification() {
  // Удаляем существующее уведомление, если есть
  const existing = document.getElementById("chat-toast-notification");
  if (existing) {
    existing.classList.remove("show");
    setTimeout(() => {
      if (existing.parentElement) {
        existing.remove();
      }
    }, 300);
  }

  // Создаем новое уведомление
  const toast = document.createElement("div");
  toast.id = "chat-toast-notification";
  toast.className = "chat-toast-notification";
  toast.innerHTML = `
    <div class="d-flex align-items-center gap-2">
      <div class="chat-toast-icon">
        <i class="bi bi-chat-dots-fill"></i>
      </div>
      <div>
        <div class="fw-semibold small">Есть непрочитанное сообщение</div>
        <div class="small text-muted">${chatUnreadCount === 1 ? '1 новое сообщение' : `${chatUnreadCount} новых сообщений`}</div>
      </div>
      <button type="button" class="btn-close btn-close-sm ms-auto" onclick="event.stopPropagation(); this.parentElement.parentElement.remove()" aria-label="Закрыть"></button>
    </div>
  `;

  document.body.appendChild(toast);

  // Анимация появления
  setTimeout(() => {
    toast.classList.add("show");
  }, 10);

  // Автоматически скрываем через 5 секунд
  setTimeout(() => {
    if (toast.parentElement) {
      toast.classList.remove("show");
      setTimeout(() => {
        if (toast.parentElement) {
          toast.remove();
        }
      }, 300);
    }
  }, 5000);

  // При клике на уведомление открываем чат
  toast.addEventListener("click", (e) => {
    if (e.target.classList.contains("btn-close")) return;
    toggleChatModal();
    toast.classList.remove("show");
    setTimeout(() => {
      if (toast.parentElement) {
        toast.remove();
      }
    }, 300);
  });
}

async function sendChatMessage() {
  if (chatSendInflight) return;
  const input = $("chat-message-input");
  const messageText = (input?.value || "").trim();
  const fileId = chatFileId;

  if (!messageText && !fileId) return;
  if (!currentChatChannel) {
    alert("Выберите канал чата.");
    return;
  }

  try {
    chatSendInflight = true;
    const sendBtn = $("chat-send-btn");
    if (sendBtn) sendBtn.disabled = true;
    await apiPost("/api/chat/messages", {
      group_id: currentChatChannel.id,
      message_text: messageText,
      file_id: fileId,
    });

    if (input) input.value = "";
    chatFileId = null;
    const fileName = $("chat-file-name");
    if (fileName) fileName.textContent = "";

    // Обновляем сообщения без показа уведомления (мы сами отправили) - принудительно, чтобы показать наше сообщение
    await loadChatMessages(false, true);
  } catch (e) {
    alert(`Ошибка отправки: ${e.message || e}`);
  } finally {
    chatSendInflight = false;
    const sendBtn = $("chat-send-btn");
    if (sendBtn) sendBtn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initChatModernUi();
  const input = $("chat-message-input");
  if (input) {
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        sendChatMessage();
      }
    });
  }
  document.querySelectorAll(".chat-prompt-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const prompt = btn.getAttribute("data-prompt") || "";
      const inputEl = $("chat-message-input");
      if (!inputEl || !prompt) return;
      inputEl.value = prompt;
      inputEl.focus();
    });
  });

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".chat-ai-feedback-btn");
    if (!btn) return;
    e.preventDefault();
    const row = btn.closest(".chat-ai-feedback");
    if (!row) return;
    const messageId = parseInt(row.getAttribute("data-message-id"), 10);
    const groupId = parseInt(row.getAttribute("data-group-id"), 10);
    const want = parseInt(btn.getAttribute("data-rating"), 10);
    if (!messageId || !groupId) return;
    const upEl = row.querySelector(".chat-ai-feedback-up");
    const downEl = row.querySelector(".chat-ai-feedback-down");
    if (!upEl || !downEl) return;
    const cur = upEl.classList.contains("active")
      ? 1
      : downEl.classList.contains("active")
        ? -1
        : 0;
    let rating = want;
    if (cur === want) rating = 0;
    let comment = "";
    if (rating === -1) {
      const c = window.prompt(
        "Что не так с ответом? Коротко, по делу (необязательно, для датасета дообучения). Отмена — не отправлять оценку.",
        ""
      );
      if (c === null) {
        return;
      }
      comment = String(c).trim();
    }
    try {
      const payload = { message_id: messageId, group_id: groupId, rating };
      if (comment) payload.comment = comment;
      await apiPost("/api/chat/ai-feedback", payload);
      if (rating === 0) {
        upEl.classList.remove("active");
        downEl.classList.remove("active");
        upEl.setAttribute("aria-pressed", "false");
        downEl.setAttribute("aria-pressed", "false");
      } else if (rating === 1) {
        upEl.classList.add("active");
        downEl.classList.remove("active");
        upEl.setAttribute("aria-pressed", "true");
        downEl.setAttribute("aria-pressed", "false");
      } else {
        downEl.classList.add("active");
        upEl.classList.remove("active");
        upEl.setAttribute("aria-pressed", "false");
        downEl.setAttribute("aria-pressed", "true");
      }
    } catch (err) {
      console.warn("ai-feedback", err);
    }
  });
});

function startChatAutoRefresh() {
  if (chatMessagesInterval) clearInterval(chatMessagesInterval);

  chatMessagesInterval = setInterval(async () => {
    if (document.hidden) return;
    if (chatMessagesInflight) return;
    const container = $("chat-messages-container");
    const isModalVisible = chatModal && chatModal._isShown;

    chatMessagesInflight = true;
    try {
      // Инкрементальное обновление только если чат открыт
      // Если чат закрыт, проверяем новые сообщения для уведомлений
      if (isModalVisible && container) {
        // Тихая инкрементальная загрузка - только новые сообщения
        await loadChatMessages(false, false);
      } else if (!isModalVisible) {
        // Проверяем новые сообщения для уведомлений
        await loadChatMessages(true, false);
      }
    } catch (_) {
      // молча
    } finally {
      chatMessagesInflight = false;
    }
  }, 7000);
}

function stopChatAutoRefresh() {
  if (chatMessagesInterval) {
    clearInterval(chatMessagesInterval);
    chatMessagesInterval = null;
  }
}

function startChatNotifyPolling() {
  if (chatNotifyInterval) clearInterval(chatNotifyInterval);
  const checkNewMessages = async () => {
    if (document.hidden) return;
    if (chatNotifyInflight) return;
    const isModalVisible = chatModal && chatModal._isShown;
    if (isModalVisible) return;
    chatNotifyInflight = true;
    try {
      await loadChatMessages(true);
    } catch (_) {
      // молча
    } finally {
      chatNotifyInflight = false;
    }
  };
  chatNotifyInterval = setInterval(checkNewMessages, 20000);
}

function stopChatNotifyPolling() {
  if (chatNotifyInterval) {
    clearInterval(chatNotifyInterval);
    chatNotifyInterval = null;
  }
}

// Экспортируем функцию для глобального доступа
if (typeof window !== 'undefined') {
  window.toggleChatModal = toggleChatModal;
  window.showChatNotification = showChatNotification;
}

// Инициализация при загрузке страницы - проверка новых сообщений (отложенно, чтобы не мешать оператору)
(function initChatNotifications() {
  function bootstrapChatNotify() {
    setTimeout(() => {
      loadChatMessages(false);
    }, 3500);
    startChatNotifyPolling();
  }
  const schedule = () => {
    if (typeof requestIdleCallback === "function") {
      requestIdleCallback(bootstrapChatNotify, { timeout: 6000 });
    } else {
      setTimeout(bootstrapChatNotify, 4000);
    }
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", schedule);
  } else {
    schedule();
  }
})();

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopChatNotifyPolling();
    stopChatAutoRefresh();
    return;
  }
  if (chatModal && chatModal._isShown) {
    startChatAutoRefresh();
  } else {
    startChatNotifyPolling();
  }
});

// File upload handler
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    const fileInput = $("chat-file-input");
    if (fileInput) {
      fileInput.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const fileName = $("chat-file-name");
        if (fileName) fileName.textContent = `Загрузка: ${file.name}...`;

        try {
          const formData = new FormData();
          formData.append("file", file);

          const res = await fetch("/api/chat/files", {
            method: "POST",
            body: formData,
          });

          const data = await res.json().catch(() => ({}));
          if (!res.ok || data.ok === false) {
            throw new Error(data.error || `HTTP ${res.status}`);
          }

          chatFileId = data.file_id;
          if (fileName) fileName.textContent = `Файл: ${file.name}`;
        } catch (e) {
          alert(`Ошибка загрузки файла: ${e.message || e}`);
          if (fileName) fileName.textContent = "";
          chatFileId = null;
        }
      });
    }
  });
} else {
  const fileInput = $("chat-file-input");
  if (fileInput) {
    fileInput.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const fileName = $("chat-file-name");
      if (fileName) fileName.textContent = `Загрузка: ${file.name}...`;

      try {
        const formData = new FormData();
        formData.append("file", file);

        const res = await fetch("/api/chat/files", {
          method: "POST",
          body: formData,
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
          throw new Error(data.error || `HTTP ${res.status}`);
        }

        chatFileId = data.file_id;
        if (fileName) fileName.textContent = `Файл: ${file.name}`;
      } catch (e) {
        alert(`Ошибка загрузки файла: ${e.message || e}`);
        if (fileName) fileName.textContent = "";
        chatFileId = null;
      }
    });
  }
}
