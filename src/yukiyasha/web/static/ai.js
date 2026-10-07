"use strict";

/*
 * AI assistant page: conversation list, streamed chat, persona editor.
 * Loaded before app.js; it only defines functions and uses app.js helpers (api, toast, icon,
 * askConfirm, navigate, showView, describeError, ApiError) when they are called.
 * Everything that comes from the model or from files is rendered through textContent.
 */

const ai = {
  status: null, // { configured, problem, provider, model, assistant_name, limits, ... }
  chats: [],
  chatId: null,
  sending: false,
  wired: false,
};

const aiById = (id) => document.getElementById(id);

const AI_SETUP_EXAMPLE = [
  "YUKIYASHA_AI_BASE_URL=https://адрес-провайдера/v1",
  "YUKIYASHA_AI_MODEL=имя-модели",
  "YUKIYASHA_AI_API_KEY=ваш-ключ",
].join("\n");

/* ---------- opening the page ---------- */

async function openAi(chatId) {
  aiWire();
  await Promise.all([aiLoadStatus(), aiLoadChats()]);
  if (chatId) {
    await aiShowChat(chatId);
  } else {
    ai.chatId = null;
    aiRenderHello();
    aiRenderChatList();
  }
}

function aiWire() {
  if (ai.wired) return;
  ai.wired = true;
  aiById("ai-new").addEventListener("click", () => navigate({ ai: true }));
  aiById("ai-persona-btn").addEventListener("click", () => void aiOpenPersona());
  aiById("form-persona").addEventListener("submit", (event) => void aiSavePersona(event));
  aiById("ai-form").addEventListener("submit", (event) => {
    event.preventDefault();
    void aiSend();
  });
  aiById("ai-input").addEventListener("keydown", (event) => {
    // Enter sends, Shift+Enter makes a new line; ignore Enter that confirms an IME candidate.
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void aiSend();
    }
  });
}

/* ---------- status & banner ---------- */

async function aiLoadStatus() {
  try {
    ai.status = await api("GET", "/api/ai/status");
  } catch (error) {
    ai.status = null;
    aiShowBanner(`Не удалось получить состояние помощника: ${describeError(error)}`);
    aiSetInputEnabled(false);
    return;
  }
  const status = ai.status;
  aiById("ai-title").textContent = status.assistant_name;

  const banner = aiById("ai-banner");
  if (!status.configured) {
    banner.replaceChildren();
    const title = document.createElement("strong");
    title.textContent = status.problem;
    const help = document.createElement("div");
    help.append(
      "Создайте файл ",
      Object.assign(document.createElement("code"), { textContent: "ai.env" }),
      " в папке Yukiyasha (рядом с каталогом ",
      Object.assign(document.createElement("code"), { textContent: "disk" }),
      ") и впишите строки ниже. Ключ хранится только в этом файле: на Диск, в репозиторий и в интерфейс он не попадает. После сохранения перезапустите программу.",
    );
    const example = document.createElement("pre");
    example.textContent = AI_SETUP_EXAMPLE;
    banner.append(title, help, example);
    banner.hidden = false;
    aiById("ai-privacy").textContent = "";
  } else {
    banner.hidden = true;
    aiById("ai-privacy").textContent =
      `Сообщения отправляются провайдеру ${status.provider} (модель ${status.model}). ` +
      "Данные программы (путевые листы, сотрудники, документы) помощнику не передаются.";
  }
  aiSetInputEnabled(status.configured);
}

function aiShowBanner(text) {
  const banner = aiById("ai-banner");
  banner.textContent = text;
  banner.hidden = false;
}

function aiSetInputEnabled(enabled) {
  aiById("ai-input").disabled = !enabled || ai.sending;
  aiById("ai-send").disabled = !enabled || ai.sending;
}

/* ---------- conversation list ---------- */

async function aiLoadChats() {
  try {
    ai.chats = (await api("GET", "/api/ai/conversations")).conversations;
  } catch (error) {
    ai.chats = [];
    toast(`Не удалось загрузить диалоги: ${describeError(error)}`, "error");
  }
  aiRenderChatList();
}

function aiFormatTime(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function aiRenderChatList() {
  const list = aiById("ai-chat-list");
  aiById("ai-chats-empty").hidden = ai.chats.length > 0;
  list.replaceChildren(
    ...ai.chats.map((chat) => {
      const item = document.createElement("li");
      item.className = "ai-chat-item";
      if (chat.id === ai.chatId) item.setAttribute("aria-current", "true");

      const open = document.createElement("button");
      open.type = "button";
      open.className = "ai-chat-open";
      const title = document.createElement("strong");
      title.textContent = chat.title;
      const meta = document.createElement("small");
      meta.textContent = `${aiFormatTime(chat.updated_at)} · ${chat.messages} сообщ.`;
      open.append(title, meta);
      open.addEventListener("click", () => navigate({ ai: true, chat: chat.id }));

      const del = document.createElement("button");
      del.type = "button";
      del.className = "ai-chat-del";
      del.setAttribute("aria-label", `Удалить диалог: ${chat.title}`);
      del.append(icon("i-trash"));
      del.addEventListener("click", () => void aiDeleteChat(chat));

      item.append(open, del);
      return item;
    }),
  );
}

async function aiDeleteChat(chat) {
  const confirmed = await askConfirm({
    title: "Удалить диалог?",
    text: `«${chat.title}» будет удалён без возможности восстановления.`,
    okLabel: "Удалить",
  });
  if (!confirmed) return;
  try {
    await api("DELETE", `/api/ai/conversations/${chat.id}`);
    toast("Диалог удалён");
    if (chat.id === ai.chatId) navigate({ ai: true });
    else await aiLoadChats();
  } catch (error) {
    toast(`Не удалось удалить: ${describeError(error)}`, "error");
  }
}

/* ---------- messages ---------- */

function aiRenderHello() {
  const messages = aiById("ai-messages");
  const hello = document.createElement("div");
  hello.className = "ai-hello";
  const strong = document.createElement("strong");
  strong.textContent = ai.status ? `Здравствуйте! Я — ${ai.status.assistant_name}.` : "Помощник";
  const text = document.createElement("span");
  text.textContent =
    "Напишите вопрос ниже. Личность и диалоги хранятся на вашем Диске, ответы даёт выбранная модель по вашему ключу.";
  hello.append(strong, text);
  messages.replaceChildren(hello);
  aiHideError();
}

function aiBubble(role, text, streaming = false) {
  const node = document.createElement("div");
  node.className = `ai-msg ${role}${streaming ? " streaming" : ""}`;
  node.textContent = text;
  return node;
}

function aiScrollDown() {
  const box = aiById("ai-messages");
  box.scrollTop = box.scrollHeight;
}

async function aiShowChat(chatId) {
  try {
    const chat = await api("GET", `/api/ai/conversations/${chatId}`);
    ai.chatId = chat.id;
    aiById("ai-messages").replaceChildren(...chat.messages.map((m) => aiBubble(m.role, m.content)));
    aiHideError();
    aiRenderChatList();
    aiScrollDown();
  } catch (error) {
    toast(describeError(error), "error");
    navigate({ ai: true });
  }
}

function aiShowError(message) {
  const slot = aiById("ai-error");
  slot.textContent = message;
  slot.hidden = false;
}

function aiHideError() {
  aiById("ai-error").hidden = true;
}

/* ---------- sending (server-sent events) ---------- */

/** POST the message and call ``onEvent`` for every server-sent event. */
async function aiStream(body, onEvent) {
  const response = await fetch("/api/ai/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = null;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const line of block.split("\n")) {
        if (!line.startsWith("data:")) continue;
        try {
          onEvent(JSON.parse(line.slice(5).trim()));
        } catch (error) {
          if (!(error instanceof SyntaxError)) throw error;
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
}

async function aiSend() {
  const input = aiById("ai-input");
  const text = input.value.trim();
  if (!text || ai.sending || !ai.status?.configured) return;

  ai.sending = true;
  aiSetInputEnabled(false);
  aiHideError();

  const messages = aiById("ai-messages");
  messages.querySelector(".ai-hello")?.remove();
  const userBubble = aiBubble("user", text);
  const answer = aiBubble("assistant", "", true);
  messages.append(userBubble, answer);
  aiScrollDown();

  let finished = false;
  let failure = null;
  try {
    await aiStream({ message: text, conversation_id: ai.chatId }, (event) => {
      if (event.type === "meta") {
        if (!ai.chatId) {
          ai.chatId = event.conversation_id;
          history.replaceState(null, "", `#ai=${encodeURIComponent(ai.chatId)}`);
          state.lastHash = window.location.hash;
        }
      } else if (event.type === "delta") {
        answer.textContent += event.text;
        aiScrollDown();
      } else if (event.type === "error") {
        failure = event.message;
      } else if (event.type === "done") {
        finished = true;
      }
    });
    if (!finished && !failure) failure = "Ответ оборвался, повторите попытку";
  } catch (error) {
    failure = describeError(error);
  }

  answer.classList.remove("streaming");
  ai.sending = false;
  if (failure) {
    // Nothing was saved on the server, so take the exchange back and keep the text for a retry.
    userBubble.remove();
    answer.remove();
    ai.chatId = ai.chats.some((chat) => chat.id === ai.chatId) ? ai.chatId : null;
    if (!ai.chatId) {
      history.replaceState(null, "", "#ai");
      state.lastHash = window.location.hash;
      if (!aiById("ai-messages").childElementCount) aiRenderHello();
    }
    aiShowError(failure);
    input.value = text;
  } else {
    input.value = "";
    await aiLoadChats();
  }
  aiSetInputEnabled(Boolean(ai.status?.configured));
  input.focus();
}

/* ---------- persona ---------- */

async function aiOpenPersona() {
  try {
    aiById("persona-text").value = (await api("GET", "/api/ai/persona")).text;
  } catch (error) {
    toast(`Не удалось открыть личность: ${describeError(error)}`, "error");
    return;
  }
  aiById("persona-error").hidden = true;
  aiById("dlg-persona").returnValue = "";
  aiById("dlg-persona").showModal();
  aiById("persona-text").focus();
}

async function aiSavePersona(event) {
  event.preventDefault();
  const button = aiById("persona-save");
  button.disabled = true;
  try {
    await api("PUT", "/api/ai/persona", { body: { text: aiById("persona-text").value } });
    aiById("dlg-persona").close("saved");
    toast("Личность сохранена");
  } catch (error) {
    const slot = aiById("persona-error");
    slot.textContent = describeError(error);
    slot.hidden = false;
  } finally {
    button.disabled = false;
  }
}
