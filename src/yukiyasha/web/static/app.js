"use strict";

/* Yukiyasha workspace UI. All user-controlled strings are rendered through textContent. */

const {
  plural,
  formatSize,
  byteLength,
  parentOf,
  baseName,
  joinPath,
  sectionFor,
  routeToHash,
  parseHash,
} = window.YukiUtil;

const MAX_TEXT_BYTES = 1_048_576;
const PROTECTED_PATHS = new Set(["projects", "projects/work", "projects/home"]);
const SECTIONS = {
  "projects/work": "Рабочие",
  "projects/home": "Домашние",
  "": "Весь диск",
};
const STATUS_POLL_MS = 20_000;

const $ = (selector) => document.querySelector(selector);
const els = {
  main: $("#main"),
  viewFiles: $("#view-files"),
  viewSystem: $("#view-system"),
  navItems: document.querySelectorAll(".nav-item"),
  status: $("#status"),
  crumbs: $("#crumbs"),
  entries: $("#entries"),
  listEmpty: $("#list-empty"),
  count: $("#count"),
  filter: $("#filter"),
  btnRefresh: $("#btn-refresh"),
  btnNew: $("#btn-new"),
  editorEmpty: $("#editor-empty"),
  editor: $("#editor"),
  editorName: $("#editor-name"),
  editorPath: $("#editor-path"),
  editorDirty: $("#editor-dirty"),
  editorText: $("#editor-text"),
  editorStats: $("#editor-stats"),
  editorError: $("#editor-error"),
  btnSave: $("#btn-save"),
  btnDelete: $("#btn-delete"),
  btnBack: $("#btn-back"),
  runtimeState: $("#runtime-state"),
  version: $("#version"),
  environment: $("#environment"),
  startedAt: $("#started-at"),
  modules: $("#modules"),
  telemetry: $("#telemetry"),
  btnSystemRefresh: $("#btn-system-refresh"),
  dlgNew: $("#dlg-new"),
  formNew: $("#form-new"),
  newPath: $("#new-path"),
  newSubmit: $("#new-submit"),
  newNote: $("#dlg-new-note"),
  newError: $("#dlg-new-error"),
  dlgConfirm: $("#dlg-confirm"),
  confirmTitle: $("#dlg-confirm-title"),
  confirmText: $("#dlg-confirm-text"),
  confirmOk: $("#dlg-confirm-ok"),
  toasts: $("#toasts"),
};

const state = {
  view: "files",
  dir: "projects/work",
  entries: [],
  file: null, // { path, original }
  listController: null,
  fileController: null,
  lastHash: "",
};

/* ---------- helpers ---------- */

const KNOWN_ERRORS = {
  "File not found": "Файл не найден",
  "Directory not found": "Папка не найдена",
  "File already exists": "Такой файл уже существует",
  "Target path is a directory": "По этому пути находится папка",
  "Path is a directory": "Это папка, а не файл",
  "Path is not a directory": "Это файл, а не папка",
  "Parent path is not a directory": "Часть пути — файл, а не папка",
  "Directory is not empty": "Папка не пуста — сначала удалите её содержимое",
  "Text content exceeds the 1 MiB limit": "Файл больше 1 МБ",
  "Text file exceeds the 1 MiB limit": "Файл больше 1 МБ",
  "File is not valid UTF-8 text": "Файл не является текстом в кодировке UTF-8",
  "Content must be valid UTF-8 text": "Текст содержит недопустимые символы",
  "Built-in project directories cannot be deleted": "Встроенные папки проектов удалить нельзя",
  "The disk root cannot be deleted": "Корень диска удалить нельзя",
  "A file path is required": "Укажите имя файла",
  "Path contains characters unsupported on Windows": "В имени есть недопустимые символы: < > : \" \\ | ? *",
  "Path components cannot end with a space or dot": "Имя не может заканчиваться пробелом или точкой",
  "Reserved Windows device names are not allowed": "Это имя зарезервировано в Windows (CON, NUL, COM1…)",
  "Backslashes are not allowed in portable disk paths": "Используйте «/» вместо «\\»",
  "Symlinks are not allowed in Yukiyasha Disk paths": "Символические ссылки не поддерживаются",
  "Path traversal is not allowed": "Выходить за пределы диска (..) нельзя",
  "Absolute paths are not allowed": "Абсолютные пути не разрешены",
  "Empty path components are not allowed": "В пути есть пустая часть",
  "Control characters are not allowed in paths": "В пути есть управляющие символы",
  "NUL characters are not allowed in paths": "В пути есть недопустимый символ",
  "Filesystem permission denied": "Нет доступа к файлу",
  "Request body too large": "Файл слишком большой для отправки",
  "Origin is not allowed": "Запрос отклонён: недопустимый источник",
};

class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

function describeError(error) {
  if (error instanceof ApiError) {
    if (typeof error.detail === "string") {
      if (error.detail.startsWith("Yukiyasha Disk is not ready")) return "Диск ещё не готов";
      return KNOWN_ERRORS[error.detail] ?? error.detail;
    }
    if (error.status === 422) return "Некорректные данные запроса";
    return `Ошибка сервера (${error.status})`;
  }
  if (error instanceof TypeError) return "Нет связи с ядром Yukiyasha";
  return error?.message || "Неизвестная ошибка";
}

async function api(method, path, { params, body, signal } = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params ?? {})) url.searchParams.set(key, value);

  const response = await fetch(url, {
    method,
    signal,
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    /* empty or non-JSON body */
  }
  if (!response.ok) throw new ApiError(response.status, payload?.detail);
  return payload;
}

function isAbort(error) {
  return error?.name === "AbortError";
}









function icon(id, className = "icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${id}`);
  svg.append(use);
  return svg;
}

function toast(message, kind = "ok") {
  const node = document.createElement("div");
  node.className = `toast${kind === "error" ? " error" : ""}`;
  node.textContent = message;
  els.toasts.append(node);
  setTimeout(() => node.remove(), kind === "error" ? 6500 : 3200);
}

function isDirty() {
  return Boolean(state.file) && els.editorText.value !== state.file.original;
}

/* ---------- confirm dialog ---------- */

function askConfirm({ title, text, okLabel, danger = true }) {
  if (els.dlgConfirm.open) return Promise.resolve(false); // never stack two modals
  return new Promise((resolve) => {
    els.confirmTitle.textContent = title;
    els.confirmText.textContent = text;
    els.confirmOk.textContent = okLabel;
    els.confirmOk.value = "ok";
    els.confirmOk.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;
    els.dlgConfirm.returnValue = "";
    els.dlgConfirm.addEventListener(
      "close",
      () => resolve(els.dlgConfirm.returnValue === "ok"),
      { once: true },
    );
    els.dlgConfirm.showModal();
  });
}

document.querySelectorAll("dialog [data-close]").forEach((button) => {
  button.addEventListener("click", () => button.closest("dialog").close("cancel"));
});

/* ---------- routing ---------- */



function navigate(route) {
  const hash = routeToHash(route);
  if (hash === window.location.hash) {
    void applyRoute(route);
  } else {
    window.location.hash = hash;
  }
}

async function applyRoute(route) {
  const sameFile = route.file && state.file && route.file === state.file.path;
  // Opening the system page keeps the editor (and its text) alive, so nothing is lost yet.
  if (isDirty() && !sameFile && !route.system) {
    const discard = await askConfirm({
      title: "Есть несохранённые изменения",
      text: `Изменения в «${baseName(state.file.path)}» будут потеряны.`,
      okLabel: "Отбросить изменения",
    });
    if (!discard) {
      history.replaceState(null, "", state.lastHash || window.location.pathname);
      return;
    }
  }
  state.lastHash = window.location.hash;

  if (route.system) {
    showView("system");
    updateNav("system");
    await loadSystem();
    return;
  }

  showView("files");
  if (sameFile) {
    updateNav(sectionFor(state.dir));
    renderCrumbs();
    return;
  }

  const dir = route.file ? parentOf(route.file) : route.dir;
  const dirChanged = dir !== state.dir || !state.entries.length;
  if (dir !== state.dir) {
    state.entries = [];
    els.filter.value = "";
  }
  state.dir = dir;
  updateNav(sectionFor(dir));
  renderCrumbs();

  if (route.file) {
    await Promise.all([dirChanged ? loadDir() : Promise.resolve(), openFile(route.file)]);
  } else {
    closeEditor();
    await loadDir();
  }
}

window.addEventListener("hashchange", () => void applyRoute(parseHash(window.location.hash)));

function showView(view) {
  state.view = view;
  els.viewFiles.hidden = view !== "files";
  els.viewSystem.hidden = view !== "system";
}

function updateNav(section) {
  els.navItems.forEach((item) => {
    if (item.dataset.section === section) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
}

els.navItems.forEach((item) => {
  item.addEventListener("click", () => {
    const section = item.dataset.section;
    navigate(section === "system" ? { system: true } : { dir: section });
  });
});

/* ---------- file listing ---------- */

function renderCrumbs() {
  const section = sectionFor(state.dir);
  const rootLabel = SECTIONS[section];
  const rest = state.dir.slice(section.length).split("/").filter(Boolean);

  const parts = [{ label: rootLabel, path: section }];
  let acc = section;
  for (const segment of rest) {
    acc = acc ? `${acc}/${segment}` : segment;
    parts.push({ label: segment, path: acc });
  }

  els.crumbs.replaceChildren();
  parts.forEach((part, index) => {
    if (index > 0) els.crumbs.append(icon("i-chevron", "icon sep"));
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = part.label;
    button.title = part.path || "Корень диска";
    if (index === parts.length - 1) button.setAttribute("aria-current", "location");
    button.addEventListener("click", () => navigate({ dir: part.path }));
    els.crumbs.append(button);
  });
}

function showSkeleton() {
  const wrap = document.createElement("li");
  wrap.className = "skeleton";
  wrap.setAttribute("aria-hidden", "true");
  wrap.append(...Array.from({ length: 4 }, () => document.createElement("i")));
  els.entries.replaceChildren(wrap);
  els.listEmpty.hidden = true;
}

async function loadDir() {
  state.listController?.abort();
  const controller = new AbortController();
  state.listController = controller;
  const requestedDir = state.dir;

  if (!state.entries.length) showSkeleton();

  try {
    const data = await api("GET", "/api/disk", {
      params: { path: requestedDir },
      signal: controller.signal,
    });
    if (controller.signal.aborted || requestedDir !== state.dir) return;
    state.entries = data.entries;
    renderEntries();
  } catch (error) {
    if (isAbort(error) || requestedDir !== state.dir) return;
    state.entries = [];
    els.entries.replaceChildren();
    els.count.textContent = "";
    showListMessage(
      "Не удалось открыть папку",
      describeError(error),
      requestedDir === sectionFor(requestedDir) ? "Повторить" : "К корню раздела",
      () => navigate({ dir: sectionFor(requestedDir) }),
    );
  }
}

function showListMessage(title, text, actionLabel, action) {
  els.listEmpty.replaceChildren();
  const strong = document.createElement("strong");
  strong.textContent = title;
  const p = document.createElement("p");
  p.textContent = text;
  els.listEmpty.append(strong, p);
  if (actionLabel) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn";
    button.textContent = actionLabel;
    button.addEventListener("click", action);
    els.listEmpty.append(button);
  }
  els.listEmpty.hidden = false;
}

function renderEntries() {
  const query = els.filter.value.trim().toLowerCase();
  const visible = query
    ? state.entries.filter((entry) => entry.name.toLowerCase().includes(query))
    : state.entries;

  const total = state.entries.length;
  const noun = (n) => plural(n, "объект", "объекта", "объектов");
  els.count.textContent = query
    ? `${visible.length} из ${total}`
    : `${total} ${noun(total)}`;

  els.entries.replaceChildren(
    ...visible.map((entry) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      const isDir = entry.type === "directory";
      button.className = `entry${isDir ? " is-dir" : ""}`;
      if (state.file?.path === entry.path) button.setAttribute("aria-current", "true");

      const name = document.createElement("span");
      name.className = "name";
      name.textContent = entry.name;
      if (PROTECTED_PATHS.has(entry.path)) {
        const lock = icon("i-lock", "icon lock");
        lock.setAttribute("aria-label", "Встроенная папка");
        name.append(lock);
      }

      const meta = document.createElement("span");
      meta.className = "meta";
      meta.textContent = isDir ? "папка" : formatSize(entry.size);

      button.append(icon(isDir ? "i-folder" : "i-file"), name, meta);
      button.addEventListener("click", () =>
        navigate(isDir ? { dir: entry.path } : { file: entry.path }),
      );
      item.append(button);
      return item;
    }),
  );

  if (!visible.length) {
    if (query) {
      showListMessage("Ничего не найдено", `Нет объектов, содержащих «${els.filter.value.trim()}».`);
    } else {
      showListMessage(
        "Здесь пока пусто",
        "Создайте первый файл — папки появятся автоматически, если указать путь вида «папка/файл.txt».",
        "Новый файл",
        openNewDialog,
      );
    }
  } else {
    els.listEmpty.hidden = true;
  }
}

els.filter.addEventListener("input", renderEntries);
els.btnRefresh.addEventListener("click", () => void loadDir());

/* ---------- editor ---------- */

function closeEditor() {
  state.fileController?.abort();
  state.file = null;
  els.editor.hidden = true;
  els.editorEmpty.hidden = false;
  els.editorError.hidden = true;
  els.main.dataset.view = "list";
  markCurrentEntry();
}

function markCurrentEntry() {
  els.entries.querySelectorAll(".entry").forEach((node) => node.removeAttribute("aria-current"));
  if (!state.file) return;
  const query = els.filter.value.trim().toLowerCase();
  const visible = query
    ? state.entries.filter((entry) => entry.name.toLowerCase().includes(query))
    : state.entries;
  const position = visible.findIndex((entry) => entry.path === state.file.path);
  els.entries.querySelectorAll(".entry")[position]?.setAttribute("aria-current", "true");
}

async function openFile(path) {
  state.fileController?.abort();
  const controller = new AbortController();
  state.fileController = controller;

  try {
    const data = await api("GET", "/api/disk/file", { params: { path }, signal: controller.signal });
    if (controller.signal.aborted) return;
    state.file = { path, original: data.content };
    els.editorText.value = data.content;
    els.editorName.textContent = baseName(path);
    els.editorPath.textContent = path;
    els.editorEmpty.hidden = true;
    els.editor.hidden = false;
    els.main.dataset.view = "editor";
    els.editorError.hidden = true;
    updateEditorState();
    markCurrentEntry();
    if (window.matchMedia("(min-width: 901px)").matches) els.editorText.focus({ preventScroll: true });
  } catch (error) {
    if (isAbort(error)) return;
    toast(describeError(error), "error");
    closeEditor();
    history.replaceState(null, "", routeToHash({ dir: state.dir }));
    state.lastHash = window.location.hash;
  }
}

function updateEditorState() {
  if (!state.file) return;
  const text = els.editorText.value;
  const bytes = byteLength(text);
  const lines = text === "" ? 0 : text.split("\n").length;
  const dirty = text !== state.file.original;
  const tooBig = bytes > MAX_TEXT_BYTES;

  els.editorDirty.hidden = !dirty;
  els.btnSave.disabled = !dirty || tooBig;

  const sizeText = `${formatSize(bytes)} из ${formatSize(MAX_TEXT_BYTES)}`;
  els.editorStats.replaceChildren();
  const size = document.createElement("span");
  size.textContent = sizeText;
  if (tooBig) size.className = "over";
  else if (bytes > MAX_TEXT_BYTES * 0.9) size.className = "near";
  els.editorStats.append(
    `${lines} ${plural(lines, "строка", "строки", "строк")} · `,
    size,
  );
  if (tooBig) {
    showEditorError("Файл больше 1 МБ — сохранить его нельзя. Сократите текст.", "size");
  } else if (!els.editorError.hidden && els.editorError.dataset.kind === "size") {
    els.editorError.hidden = true;
  }
}

function showEditorError(message, kind = "api") {
  els.editorError.textContent = message;
  els.editorError.dataset.kind = kind;
  els.editorError.hidden = false;
}

els.editorText.addEventListener("input", () => {
  if (els.editorError.dataset.kind === "api") els.editorError.hidden = true;
  updateEditorState();
});

async function saveFile() {
  if (!state.file || els.btnSave.disabled) return;
  const { path } = state.file;
  const content = els.editorText.value;
  els.btnSave.disabled = true;
  els.editorError.hidden = true;

  try {
    await api("PUT", "/api/disk/file", { body: { path, content, overwrite: true } });
    if (state.file?.path === path) state.file.original = content;
    updateEditorState();
    toast("Сохранено");
    void loadDir();
  } catch (error) {
    showEditorError(`Не удалось сохранить: ${describeError(error)}`);
    updateEditorState();
  }
}

els.btnSave.addEventListener("click", () => void saveFile());

els.btnBack.addEventListener("click", () => navigate({ dir: state.dir }));

els.btnDelete.addEventListener("click", async () => {
  if (!state.file) return;
  const { path } = state.file;
  const confirmed = await askConfirm({
    title: "Удалить файл?",
    text: `«${path}» будет удалён без возможности восстановления.`,
    okLabel: "Удалить",
  });
  if (!confirmed) return;

  try {
    await api("DELETE", "/api/disk/file", { params: { path } });
    state.file.original = els.editorText.value; // do not prompt about discarding a deleted file
    toast("Файл удалён");
    navigate({ dir: parentOf(path) });
  } catch (error) {
    toast(`Не удалось удалить: ${describeError(error)}`, "error");
  }
});

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s" && state.file) {
    event.preventDefault();
    void saveFile();
  }
});

window.addEventListener("beforeunload", (event) => {
  if (isDirty()) {
    event.preventDefault();
    event.returnValue = "";
  }
});

/* ---------- new file ---------- */

function openNewDialog() {
  els.newNote.textContent = `Файл будет создан в «${state.dir || "корне диска"}». Подпапки создаются автоматически.`;
  els.newPath.value = "";
  els.newError.hidden = true;
  els.dlgNew.showModal();
  els.newPath.focus();
}

els.btnNew.addEventListener("click", openNewDialog);

els.formNew.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = els.newPath.value.trim();
  if (!name) {
    els.newError.textContent = "Укажите имя файла.";
    els.newError.hidden = false;
    return;
  }
  const path = joinPath(state.dir, name);

  els.newSubmit.disabled = true;
  try {
    await api("PUT", "/api/disk/file", { body: { path, content: "", overwrite: false } });
    els.dlgNew.close("created");
    toast("Файл создан");
    navigate({ file: path });
  } catch (error) {
    els.newError.textContent = describeError(error);
    els.newError.hidden = false;
  } finally {
    els.newSubmit.disabled = false;
  }
});

/* ---------- system ---------- */

const RUNTIME_LABELS = {
  ready: "Работает",
  starting: "Запускается",
  degraded: "Деградировал",
  stopped: "Остановлен",
};

const MODULE_LABELS = {
  ready: ["Работает", "ok"],
  registered: ["Зарегистрирован", "warn"],
  stopped: ["Остановлен", "warn"],
  failed: ["Ошибка", "bad"],
};

function setStatus(kind, text) {
  els.status.classList.toggle("online", kind === "online");
  els.status.classList.toggle("offline", kind === "offline");
  els.status.querySelector("span").textContent = text;
}

async function refreshRuntime() {
  try {
    const data = await api("GET", "/api/runtime");
    els.runtimeState.textContent = RUNTIME_LABELS[data.state] ?? data.state;
    els.version.textContent = `v${data.version}`;
    els.environment.textContent = data.environment;
    els.startedAt.textContent = data.started_at
      ? new Date(data.started_at).toLocaleString("ru-RU")
      : "—";
    els.telemetry.textContent = JSON.stringify(data, null, 2);
    if (data.state === "ready") setStatus("online", "Ядро активно");
    else setStatus("warn", `Ядро: ${RUNTIME_LABELS[data.state] ?? data.state}`);
    return true;
  } catch (error) {
    setStatus("offline", "Нет связи");
    els.telemetry.textContent = `Ошибка: ${describeError(error)}`;
    return false;
  }
}

function renderModules(snapshots) {
  els.modules.replaceChildren(
    ...snapshots.map((snapshot) => {
      const { manifest, state: moduleState, health } = snapshot;
      const card = document.createElement("article");
      card.className = "module";

      const head = document.createElement("div");
      head.className = "module-head";
      const title = document.createElement("h3");
      title.textContent = manifest.name;
      const id = document.createElement("small");
      id.textContent = `${manifest.module_id} · v${manifest.version}`;
      title.append(id);
      const [label, tone] = MODULE_LABELS[moduleState] ?? [moduleState, "warn"];
      const badge = document.createElement("span");
      badge.className = `state ${tone}`;
      badge.textContent = label;
      head.append(title, badge);

      const description = document.createElement("p");
      description.textContent = manifest.description;

      const chips = document.createElement("div");
      chips.className = "chips";
      for (const permission of manifest.permissions) {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = permission;
        chips.append(chip);
      }

      const details = document.createElement("dl");
      const addRow = (term, value) => {
        const dt = document.createElement("dt");
        dt.textContent = term;
        const dd = document.createElement("dd");
        dd.textContent = value;
        details.append(dt, dd);
      };
      if (health?.root) addRow("Каталог", health.root);
      if (health?.error) addRow("Ошибка", health.error);

      card.append(head, description, chips, details);
      return card;
    }),
  );
}

async function loadSystem() {
  const ok = await refreshRuntime();
  if (!ok) return;
  try {
    renderModules(await api("GET", "/api/modules"));
  } catch (error) {
    els.modules.textContent = `Не удалось загрузить модули: ${describeError(error)}`;
  }
}

els.btnSystemRefresh.addEventListener("click", () => void loadSystem());

setInterval(() => {
  if (document.hidden) return;
  if (state.view === "system") void loadSystem();
  else void refreshRuntime();
}, STATUS_POLL_MS);

/* ---------- boot ---------- */

(function boot() {
  const route = parseHash(window.location.hash);
  if (!window.location.hash) history.replaceState(null, "", routeToHash(route));
  void refreshRuntime();
  void applyRoute(route);
})();
