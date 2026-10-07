"use strict";

/*
 * AI assistant page: conversation list, streamed chat, persona editor.
 * Loaded before app.js; it only defines functions and uses app.js helpers (api, toast, icon,
 * askConfirm, navigate, showView, describeError, ApiError) when they are called.
 * Everything that comes from the model or from files is rendered through textContent.
 */

const proposalReview = YukiProposal;
const documentPresentation = YukiDocuments;

const ai = {
  status: null, // { configured, problem, provider, model, assistant_name, limits, ... }
  chats: [],
  proposals: [],
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
  await Promise.all([aiLoadStatus(), aiLoadChats(), aiLoadProposals()]);
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
      "Для ответов по Примавтодору помощник может передавать провайдеру разрешённые " +
      "read-only данные; чувствительные поля маскируются. Изменения применяются только " +
      "после отдельного подтверждения предложения.";
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
  aiRenderProposalCards();
  aiHideError();
}

async function aiHydrateDocumentPreview(card, doc) {
  if (doc.preview) return;
  try {
    const file = await api("GET", "/api/disk/file", { params: { path: doc.path } });
    const preview = documentPresentation.previewText(file.content);
    if (!preview || !card.isConnected) return;
    const body = card.querySelector(".ai-document-body");
    const meta = card.querySelector(".ai-document-meta");
    const paragraph = document.createElement("p");
    paragraph.className = "ai-document-preview";
    paragraph.textContent = preview;
    body.insertBefore(paragraph, meta);
  } catch {
    // The card is still useful as document metadata even if preview cannot be loaded.
  }
}

function aiDocumentCard(rawDocument) {
  const doc = documentPresentation.normalize(rawDocument);
  if (!doc) return null;

  const card = document.createElement("article");
  card.className = "ai-document-card";

  const page = document.createElement("div");
  page.className = "ai-document-page";
  const format = document.createElement("span");
  format.className = "ai-document-format";
  format.textContent = doc.extension;
  const lines = document.createElement("span");
  lines.className = "ai-document-page-lines";
  lines.setAttribute("aria-hidden", "true");
  page.append(format, lines);

  const body = document.createElement("div");
  body.className = "ai-document-body";
  const eyebrow = document.createElement("span");
  eyebrow.className = "ai-document-eyebrow";
  eyebrow.textContent = doc.sectionTitle;
  const title = document.createElement("strong");
  title.className = "ai-document-title";
  title.textContent = doc.title;
  body.append(eyebrow, title);

  if (doc.preview) {
    const preview = document.createElement("p");
    preview.className = "ai-document-preview";
    preview.textContent = doc.preview;
    body.append(preview);
  }

  const meta = document.createElement("div");
  meta.className = "ai-document-meta";
  const type = document.createElement("span");
  type.textContent = doc.extension;
  meta.append(type);
  if (doc.size) {
    const size = document.createElement("span");
    size.textContent = doc.size;
    meta.append(size);
  }
  body.append(meta);

  const action = document.createElement("button");
  action.type = "button";
  action.className = "ai-document-open";
  action.setAttribute("aria-label", `Открыть документ «${doc.title}»`);
  action.innerHTML = "<span>Открыть</span><span aria-hidden=\"true\">↗</span>";
  action.addEventListener("click", () => navigate({ file: doc.path }));

  card.append(page, body, action);
  void aiHydrateDocumentPreview(card, doc);
  return card;
}

function aiAppendDocuments(node, documents) {
  if (!Array.isArray(documents) || !documents.length) return;
  node.querySelector(".ai-document-list")?.remove();
  const list = document.createElement("div");
  list.className = "ai-document-list";
  list.setAttribute("aria-label", "Документы");
  for (const rawDocument of documents) {
    const card = aiDocumentCard(rawDocument);
    if (card) list.append(card);
  }
  if (list.childElementCount) node.append(list);
}

function aiBubble(role, text, streaming = false, documents = []) {
  const node = document.createElement("div");
  node.className = `ai-msg ${role}${streaming ? " streaming" : ""}`;
  const copy = document.createElement("div");
  copy.className = "ai-msg-copy";
  copy.textContent = text;
  node.append(copy);
  aiAppendDocuments(node, documents);
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
    aiById("ai-messages").replaceChildren(
      ...chat.messages.map((m) => aiBubble(m.role, m.content, false, m.documents)),
    );
    aiRenderProposalCards();
    aiHideError();
    aiRenderChatList();
    aiScrollDown();
  } catch (error) {
    toast(describeError(error), "error");
    navigate({ ai: true });
  }
}

async function aiLoadProposals() {
  try {
    ai.proposals = (await api("GET", "/api/proposals")).proposals ?? [];
  } catch (error) {
    ai.proposals = [];
    toast(`Не удалось загрузить предложения: ${describeError(error)}`, "error");
  }
  aiRenderProposalCards();
}

function aiProposalStatusClass(status) {
  return ["pending", "applied", "rejected", "stale"].includes(status)
    ? status
    : "unknown";
}

function aiProposalCard(proposal) {
  const card = document.createElement("article");
  card.className = `ai-proposal ${aiProposalStatusClass(proposal.status)}`;
  card.dataset.proposalId = proposal.id;

  const head = document.createElement("div");
  head.className = "ai-proposal-head";
  const title = document.createElement("div");
  const eyebrow = document.createElement("span");
  eyebrow.className = "ai-proposal-eyebrow";
  eyebrow.textContent = `${proposalReview.operationLabel(proposal.operation)} · ${proposalReview.kindLabel(proposal.kind)}`;
  const strong = document.createElement("strong");
  strong.textContent = proposal.target?.label || proposal.record_id || proposal.id;
  title.append(eyebrow, strong);

  const status = document.createElement("span");
  status.className = `ai-proposal-status ${aiProposalStatusClass(proposal.status)}`;
  status.textContent = proposalReview.statusLabel(proposal.status);
  head.append(title, status);
  card.append(head);

  if (proposal.reason) {
    const reason = document.createElement("p");
    reason.className = "ai-proposal-reason";
    reason.textContent = proposal.reason;
    card.append(reason);
  }

  const diff = proposalReview.buildProposalDiff(proposal);
  if (diff.length) {
    const table = document.createElement("div");
    table.className = "ai-proposal-diff";
    for (const change of diff) {
      const row = document.createElement("div");
      row.className = "ai-proposal-diff-row";

      const field = document.createElement("span");
      field.className = "ai-proposal-field";
      field.textContent = proposalReview.fieldLabel(change.field);

      const before = document.createElement("span");
      before.className = "ai-proposal-before";
      before.textContent = proposalReview.formatValue(change.before);

      const arrow = document.createElement("span");
      arrow.className = "ai-proposal-arrow";
      arrow.setAttribute("aria-hidden", "true");
      arrow.textContent = "→";

      const after = document.createElement("span");
      after.className = "ai-proposal-after";
      after.textContent = proposalReview.formatValue(change.after);

      row.append(field, before, arrow, after);
      table.append(row);
    }
    card.append(table);
  }

  const meta = document.createElement("div");
  meta.className = "ai-proposal-meta";
  meta.textContent = `ID: ${proposal.id}`;
  if (proposal.status === "stale" && proposal.result?.reason) {
    meta.textContent += ` · конфликт: ${proposal.result.reason}`;
  }
  card.append(meta);

  if (proposal.status === "pending") {
    const actions = document.createElement("div");
    actions.className = "ai-proposal-actions";

    const reject = document.createElement("button");
    reject.type = "button";
    reject.className = "btn";
    reject.textContent = "Отклонить";
    reject.addEventListener("click", () => void aiResolveProposal(proposal, "reject"));

    const approve = document.createElement("button");
    approve.type = "button";
    approve.className = "btn btn-primary";
    approve.textContent = "Подтвердить";
    approve.addEventListener("click", () => void aiResolveProposal(proposal, "approve"));

    actions.append(reject, approve);
    card.append(actions);
  }

  return card;
}

function aiRenderProposalCards() {
  const messages = aiById("ai-messages");
  if (!messages) return;
  messages.querySelector("#ai-proposal-shelf")?.remove();

  const visible = ai.proposals
    .filter((item) => item?.status === "pending" || ["applied", "rejected", "stale"].includes(item?.status))
    .slice(0, 6);
  if (!visible.length) return;

  const shelf = document.createElement("section");
  shelf.id = "ai-proposal-shelf";
  shelf.className = "ai-proposal-shelf";
  shelf.setAttribute("aria-label", "Предложения изменений");

  const heading = document.createElement("div");
  heading.className = "ai-proposal-shelf-head";
  const title = document.createElement("strong");
  title.textContent = "Предложения изменений";
  const note = document.createElement("span");
  note.textContent = "Применяются только после вашего подтверждения";
  heading.append(title, note);
  shelf.append(heading, ...visible.map(aiProposalCard));
  messages.append(shelf);
}

async function aiResolveProposal(proposal, action) {
  const approving = action === "approve";
  const confirmed = await askConfirm({
    title: approving ? "Подтвердить изменение?" : "Отклонить предложение?",
    text: approving
      ? `Предложение ${proposal.id} будет применено к данным Примавтодора.`
      : `Предложение ${proposal.id} будет окончательно отклонено.`,
    okLabel: approving ? "Подтвердить" : "Отклонить",
    danger: false,
  });
  if (!confirmed) return;

  try {
    await api("POST", `/api/proposals/${proposal.id}/${action}`);
    toast(approving ? "Изменение применено" : "Предложение отклонено");
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && error.detail?.status === "stale") {
      toast("Предложение устарело: исходная запись уже изменилась", "error");
    } else {
      toast(`Не удалось обработать предложение: ${describeError(error)}`, "error");
    }
  } finally {
    await aiLoadProposals();
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
  messages.querySelector("#ai-proposal-shelf")?.remove();
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
        answer.querySelector(".ai-msg-copy").textContent += event.text;
        aiScrollDown();
      } else if (event.type === "documents") {
        aiAppendDocuments(answer, event.documents);
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
    await Promise.all([aiLoadChats(), aiLoadProposals()]);
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
