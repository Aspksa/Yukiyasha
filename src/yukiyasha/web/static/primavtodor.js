"use strict";

/*
 * Примавтодор pages: record tables and forms (waybills, fuel, employees, vehicles) and the
 * timesheet. This script is loaded before app.js and only *defines* things: it uses the helpers
 * of app.js (api, toast, icon, askConfirm, navigate, ...) when its functions are called.
 * All user-controlled strings are rendered through textContent.
 */

const PV_UTIL = window.YukiUtil;
const PV_MODULE = "primavtodor";
const PV_WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

const PV_LEAD = {
  waybills:
    "Путевой лист связывает водителя, машину и выезд. Заправки по ГСМ и дни в табеле берутся из него.",
  fuel: "Заправка привязана к путевому листу: водитель, машина и номер топливной карты подставляются автоматически.",
  employees: "За каждым водителем закреплены топливная карта с номером и машина.",
  garage: "Машины, виды топлива и нормы расхода — по ним считается отклонение в путевых листах.",
};

const pv = {
  schema: null,
  entities: {}, // kind -> entity
  bySection: {}, // section id -> entity
  entity: null,
  records: [],
  problems: [],
  controller: null,
  editing: null, // { entity, record | null, lists }
  month: null,
  timesheet: null,
  tsController: null,
  mark: null,
  settings: null, // { season, season_label, source, updated_at }
  seasons: [],
  wired: false,
};

const pvById = (id) => document.getElementById(id);

/* ---------- schema ---------- */

async function pvEnsureSchema() {
  if (pv.schema) return pv.schema;
  const schema = await api("GET", "/api/primavtodor/schema");
  pv.schema = schema;
  pv.settings = schema.settings;
  pv.seasons = schema.seasons;
  pv.entities = {};
  pv.bySection = {};
  for (const entity of schema.entities) {
    pv.entities[entity.kind] = entity;
    pv.bySection[entity.section_id] = entity;
  }
  return schema;
}

/* ---------- summer / winter switch ---------- */

function pvBuildSeasonSwitch() {
  const wrapper = document.createElement("div");
  wrapper.className = "season-switch";
  const label = document.createElement("span");
  label.className = "season-label";
  label.textContent = "Нормы расхода ГСМ";
  const group = document.createElement("div");
  group.className = "segments";
  group.setAttribute("role", "radiogroup");
  group.setAttribute("aria-label", "Сезон норм расхода ГСМ");
  for (const season of pv.seasons) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "season-btn";
    button.dataset.season = season.value;
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(pv.settings.season === season.value));
    button.title =
      season.value === "winter" ? "Все нормы и открытые путевые листы — на зиму" : "Все нормы и открытые путевые листы — на лето";
    button.append(icon(season.value === "winter" ? "i-snow" : "i-sun"), season.label);
    button.addEventListener("click", () => void pvSetSeason(season.value));
    group.append(button);
  }
  wrapper.append(label, group);
  return wrapper;
}

/** Draw the switch into every header that has a slot for it. */
function pvRenderSeasonSwitch() {
  if (!pv.settings) return;
  for (const slot of document.querySelectorAll(".season-slot")) slot.replaceChildren(pvBuildSeasonSwitch());
}

async function pvSetSeason(season) {
  if (!pv.settings || pv.settings.season === season) return;
  for (const button of document.querySelectorAll(".season-btn")) button.disabled = true;
  try {
    const result = await api("PUT", "/api/primavtodor/settings/season", { body: { season } });
    pv.settings = result;
    const moved = result.updated_waybills;
    toast(
      moved
        ? `Сезон: ${result.season_label}. Открытых путевых листов переведено: ${moved}`
        : `Сезон: ${result.season_label}`,
    );
    if (state.view === "entity") await pvLoadEntity();
  } catch (error) {
    toast(`Не удалось переключить сезон: ${describeError(error)}`, "error");
  } finally {
    pvRenderSeasonSwitch();
  }
}

/** True for sections that have their own page (records or timesheet) instead of a plain folder. */
function pvIsInteractive(sectionId) {
  return Boolean(pv.schema) && (sectionId === pv.schema.timesheet.section_id || sectionId in pv.bySection);
}

/** Open a section page. Returns false when the section is just a folder. */
async function openPrimavtodorSection(sectionId) {
  try {
    await pvEnsureSchema();
  } catch (error) {
    toast(describeError(error), "error");
    return false;
  }
  pvWire();
  pvRenderSeasonSwitch();

  if (sectionId === pv.schema.timesheet.section_id) {
    showView("timesheet");
    await pvLoadTimesheet();
    return true;
  }
  const entity = pv.bySection[sectionId];
  if (!entity) return false;
  showView("entity");
  pvShowEntity(entity);
  await pvLoadEntity();
  return true;
}

/* ---------- wiring (once) ---------- */

function pvWire() {
  if (pv.wired) return;
  pv.wired = true;

  const goModule = () => navigate({ module: PV_MODULE });
  pvById("entity-back").addEventListener("click", goModule);
  pvById("ts-back").addEventListener("click", goModule);
  pvById("entity-files").addEventListener("click", () => navigate({ dir: pv.entity.path }));
  pvById("ts-files").addEventListener("click", () => navigate({ dir: pv.schema.timesheet.path }));
  pvById("entity-refresh").addEventListener("click", () => void pvLoadEntity());
  pvById("ts-refresh").addEventListener("click", () => void pvLoadTimesheet());
  pvById("entity-new").addEventListener("click", () => void pvOpenForm(null));
  pvById("entity-filter").addEventListener("input", pvRenderEntity);

  pvById("btn-month").addEventListener("click", () => void pvOpenMonth());
  pvById("month-input").addEventListener("change", () => void pvLoadMonth());
  pvById("month-show-dismissed").addEventListener("change", () => void pvLoadMonth());
  pvById("month-prev").addEventListener("click", () => pvShiftReview(-1));
  pvById("month-next").addEventListener("click", () => pvShiftReview(1));
  pvById("month-package").addEventListener("click", () => void pvDownloadPackage());
  pvById("ts-calendar").addEventListener("click", () => void pvOpenCalendar());
  pvById("cal-year").addEventListener("change", () => void pvShowCalendarYear());
  pvById("ts-export").addEventListener("click", () => void pvExportTimesheet());
  pvById("entity-report").addEventListener("click", pvOpenReport);
  pvById("form-report").addEventListener("submit", (event) => void pvDownloadReport(event));
  pvById("entity-import").addEventListener("click", pvOpenImport);
  pvById("import-file").addEventListener("change", () => void pvPreviewImport());
  pvById("form-import").addEventListener("submit", (event) => void pvApplyImport(event));
  pvById("entity-print-settings").addEventListener("click", () => void pvOpenPrintSettings());
  pvById("form-print").addEventListener("submit", (event) => void pvSavePrintSettings(event));
  pvById("record-print").addEventListener("click", () => void pvPrintWaybill());
  pvById("card-download").addEventListener("click", () => void pvDownloadFuelCard());

  pvById("form-record").addEventListener("submit", (event) => void pvSubmit(event));
  pvById("record-delete").addEventListener("click", () => void pvDelete());

  pvById("ts-prev").addEventListener("click", () => pvShiftMonth(-1));
  pvById("ts-next").addEventListener("click", () => pvShiftMonth(1));
  pvById("ts-today").addEventListener("click", () => pvSetMonth(PV_UTIL.currentMonth()));
  pvById("ts-month").addEventListener("change", (event) => {
    if (/^\d{4}-\d{2}$/.test(event.target.value)) pvSetMonth(event.target.value);
  });
  pvById("form-mark").addEventListener("submit", (event) => void pvSubmitMark(event));
}

/* ---------- record list ---------- */

function pvShowEntity(entity) {
  pv.entity = entity;
  pv.records = [];
  pv.problems = [];
  pvById("entity-title").textContent = entity.title;
  pvById("entity-new-label").textContent = entity.new_label;
  pvById("entity-lead").textContent = PV_LEAD[entity.section_id] ?? "";
  pvById("entity-tile").dataset.sec = entity.section_id;
  pvById("entity-icon").setAttribute("href", `#${sectionIconId(entity.section_id)}`);
  pvById("entity-filter").value = "";
  pvById("entity-print-settings").hidden = entity.kind !== "waybills";
  pvById("entity-import").hidden = entity.kind !== "fuel";
  pvById("entity-report").hidden = entity.kind !== "fuel";
  pvById("entity-table").querySelector("tbody").replaceChildren();
  pvById("entity-count").textContent = "";
  pvById("entity-empty").hidden = true;
  pvById("entity-problems").hidden = true;
}

async function pvLoadEntity() {
  const entity = pv.entity;
  pv.controller?.abort();
  const controller = new AbortController();
  pv.controller = controller;
  try {
    const data = await api("GET", `/api/primavtodor/records/${entity.kind}`, {
      signal: controller.signal,
    });
    if (controller.signal.aborted || pv.entity !== entity) return;
    pv.records = data.records;
    pv.problems = data.problems;
    pvRenderEntity();
  } catch (error) {
    if (isAbort(error) || pv.entity !== entity) return;
    pv.records = [];
    pvById("entity-table").querySelector("tbody").replaceChildren();
    pvShowEmpty("entity-empty", "Не удалось загрузить записи", describeError(error), "Повторить", () =>
      void pvLoadEntity(),
    );
  }
}

function pvShowEmpty(boxId, title, text, actionLabel, action) {
  const box = pvById(boxId);
  box.replaceChildren();
  const strong = document.createElement("strong");
  strong.textContent = title;
  const p = document.createElement("p");
  p.textContent = text;
  box.append(strong, p);
  if (actionLabel) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn";
    button.textContent = actionLabel;
    button.addEventListener("click", action);
    box.append(button);
  }
  box.hidden = false;
}

function pvRecordText(record) {
  return [record.label, ...Object.values(record.values), ...Object.values(record.labels), ...Object.values(record.computed)]
    .filter((value) => value !== null && value !== undefined)
    .map(String)
    .join(" ")
    .toLowerCase();
}

function pvRenderEntity() {
  const entity = pv.entity;
  const query = pvById("entity-filter").value.trim().toLowerCase();
  const rows = query ? pv.records.filter((record) => pvRecordText(record).includes(query)) : pv.records;
  const noun = (n) => PV_UTIL.plural(n, "запись", "записи", "записей");

  pvById("entity-count").textContent = query
    ? `${rows.length} из ${pv.records.length}`
    : `${pv.records.length} ${noun(pv.records.length)}`;

  const problems = pvById("entity-problems");
  problems.hidden = !pv.problems.length;
  if (pv.problems.length) {
    problems.textContent = `Не удалось прочитать файлы: ${pv.problems.join(", ")}. Проверьте их в «Файлах раздела».`;
  }

  const table = pvById("entity-table");
  const head = document.createElement("tr");
  for (const column of entity.columns) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = column.unit && column.kind === "number" ? `${column.label}, ${column.unit}` : column.label;
    if (column.kind === "number") th.className = "num";
    head.append(th);
  }
  table.querySelector("thead").replaceChildren(head);

  table.querySelector("tbody").replaceChildren(
    ...rows.map((record) => {
      const tr = document.createElement("tr");
      entity.columns.forEach((column, index) => {
        const td = document.createElement("td");
        if (column.kind === "number") td.className = "num";
        const cell = document.createElement(index === 0 ? "button" : "div");
        cell.className = "row-cell";
        if (index === 0) {
          cell.type = "button";
          cell.setAttribute("aria-label", `Открыть: ${record.label}`);
        }
        pvFillCell(cell, column, record);
        if (index === 0 && record.warnings.length) {
          const dot = document.createElement("span");
          dot.className = "warn-dot";
          dot.textContent = "!";
          dot.title = record.warnings.join("\n");
          cell.append(dot);
        }
        td.append(cell);
        tr.append(td);
      });
      tr.addEventListener("click", () => void pvOpenForm(record));
      return tr;
    }),
  );

  const empty = pvById("entity-empty");
  if (!rows.length) {
    if (query) {
      pvShowEmpty("entity-empty", "Ничего не найдено", `Нет записей, содержащих «${query}».`);
    } else {
      pvShowEmpty(
        "entity-empty",
        "Пока нет записей",
        `Добавьте первую запись: «${entity.new_label}».`,
        entity.new_label,
        () => void pvOpenForm(null),
      );
    }
  } else {
    empty.hidden = true;
  }
}

/** Value of a column: reference label first, then computed value, then the stored field. */
function pvColumnValue(column, record) {
  return record.labels?.[column.key] ?? record.computed?.[column.key] ?? record.values?.[column.key];
}

function pvFormatValue(kind, raw, unit = "") {
  if (raw === null || raw === undefined || raw === "") return "—";
  if (kind === "number" && typeof raw === "number") {
    return unit ? `${PV_UTIL.formatNumber(raw)} ${unit}` : PV_UTIL.formatNumber(raw);
  }
  if (kind === "date") return PV_UTIL.formatDate(raw);
  if (kind === "bool") return raw ? "да" : "нет";
  return String(raw);
}

function pvFillCell(cell, column, record) {
  const raw = pvColumnValue(column, record);
  if (column.kind === "badge" && raw) {
    const badge = document.createElement("span");
    const tone = { Закрыт: "ok", Зима: "cold", Лето: "warm" }[raw];
    badge.className = `badge${tone ? ` ${tone}` : ""}`;
    badge.textContent = String(raw);
    cell.append(badge);
    return;
  }
  const text = pvFormatValue(column.kind, raw);
  if (text === "—") {
    const dash = document.createElement("span");
    dash.className = "muted";
    dash.textContent = text;
    cell.append(dash);
  } else {
    cell.append(text);
  }
}

/* ---------- record form ---------- */

function pvSortedByLabel(records) {
  return [...records].sort((a, b) => a.label.localeCompare(b.label, "ru"));
}

async function pvLoadRefLists(entity) {
  const kinds = [...new Set(entity.fields.filter((field) => field.type === "ref").map((field) => field.ref))];
  const lists = {};
  await Promise.all(
    kinds.map(async (kind) => {
      lists[kind] = (await api("GET", `/api/primavtodor/records/${kind}`)).records;
    }),
  );
  return lists;
}

function pvNextWaybillNumber(records) {
  const numbers = records.map((record) => Number.parseInt(record.values.number, 10)).filter(Number.isFinite);
  return String(numbers.length ? Math.max(...numbers) + 1 : 1);
}

async function pvOpenForm(record) {
  const entity = pv.entity;
  let lists;
  try {
    lists = await pvLoadRefLists(entity);
  } catch (error) {
    toast(`Не удалось открыть форму: ${describeError(error)}`, "error");
    return;
  }
  pv.editing = { entity, record, lists };

  pvById("dlg-record-title").textContent = record ? `${entity.singular[0].toUpperCase()}${entity.singular.slice(1)}: ${record.label}` : entity.new_label;
  pvById("record-error").hidden = true;
  pvById("record-delete").hidden = !record;
  pvById("record-print").hidden = !(record && entity.kind === "waybills");
  pvById("record-card").hidden = !(record && entity.kind === "vehicles");
  if (!pvById("card-month").value) pvById("card-month").value = PV_UTIL.currentMonth();

  const box = pvById("record-fields");
  box.replaceChildren(
    ...entity.fields.map((field) => pvBuildField(field, record ? record.values[field.name] : undefined, lists, !record)),
  );

  if (!record) pvApplyDefaults(entity);
  pvWireForm(entity, lists, !record);
  pvRenderWarnings(record?.warnings ?? []);
  pvRenderDetails(entity, record);
  pvById("dlg-record").returnValue = "";
  pvById("dlg-record").showModal();
  const first = box.querySelector("input:not([type=checkbox]):not(:disabled), select:not(:disabled), textarea");
  first?.focus();
}

function pvApplyDefaults(entity) {
  for (const field of entity.fields) {
    if (field.type === "date" && field.name === "date") pvById(`f-${field.name}`).value = PV_UTIL.todayIso();
  }
  if (entity.kind === "waybills") {
    pvById("f-number").value = pvNextWaybillNumber(pv.records);
    pvById("f-season").value = pv.settings.season; // the switch decides the starting season
  }
}

function pvBuildField(field, value, lists, isNew) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";
  const id = `f-${field.name}`;

  let control;
  if (field.type === "bool") {
    wrapper.classList.add("field-check");
    const label = document.createElement("label");
    label.className = "check";
    control = document.createElement("input");
    control.type = "checkbox";
    control.id = id;
    control.checked = value === undefined ? Boolean(field.default) : Boolean(value);
    label.append(control, field.label);
    wrapper.append(label);
  } else {
    if (field.multiline) wrapper.classList.add("span-2");
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = field.required ? `${field.label} *` : field.label;
    wrapper.append(label);

    if (field.type === "choice" || field.type === "ref") {
      control = document.createElement("select");
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = field.type === "ref" ? "— не выбрано —" : "—";
      blank.disabled = field.type === "choice" && Boolean(field.default); // a default must stay chosen
      control.append(blank);
      const options =
        field.type === "choice"
          ? field.options
          : pvSortedByLabel(
              (lists[field.ref] ?? []).filter((target) => !field.ref_filter || target.values[field.ref_filter]),
            ).map((target) => ({ value: target.id, label: target.label }));
      for (const item of options) {
        const option = document.createElement("option");
        option.value = item.value;
        option.textContent = item.label;
        control.append(option);
      }
    } else if (field.multiline) {
      control = document.createElement("textarea");
      control.rows = 3;
      control.maxLength = field.max_len;
    } else {
      control = document.createElement("input");
      control.type = field.type === "date" ? "date" : "text";
      if (field.type === "int") control.inputMode = "numeric";
      if (field.type === "float") control.inputMode = "decimal";
      if (field.type === "text") control.maxLength = field.max_len;
    }
    control.id = id;
    control.autocomplete = "off";
    control.spellcheck = false;
    const initial = value === undefined || value === null ? (isNew ? field.default : "") : value;
    control.value = initial === null || initial === undefined ? "" : String(initial).replace(".", field.type === "float" ? "," : ".");
    if (field.type === "choice" && !control.value && field.default) control.value = String(field.default);
    wrapper.append(control);
  }

  if (field.help) {
    const help = document.createElement("small");
    help.className = "field-help";
    help.textContent = field.help;
    wrapper.append(help);
  }
  const error = document.createElement("small");
  error.className = "field-error";
  error.id = `e-${field.name}`;
  error.hidden = true;
  wrapper.append(error);
  return wrapper;
}

/** Behaviour that follows the relations: a driver brings his car, a waybill brings its card. */
function pvWireForm(entity, lists, isNew) {
  const field = (name) => pvById(`f-${name}`);

  if (entity.kind === "employees") {
    const sync = () => {
      const driver = field("is_driver").checked;
      for (const name of ["fuel_card_number", "vehicle_id"]) {
        field(name).disabled = !driver;
        if (!driver) field(name).value = "";
      }
    };
    field("is_driver").addEventListener("change", sync);
    sync();
  }

  if (entity.kind === "waybills") {
    const driverSelect = field("driver_id");
    const vehicleSelect = field("vehicle_id");
    const odometer = field("odometer_out");

    driverSelect.addEventListener("change", () => {
      const driver = (lists.employees ?? []).find((item) => item.id === driverSelect.value);
      const assigned = driver?.values.vehicle_id;
      if (assigned && (isNew || !vehicleSelect.value)) {
        vehicleSelect.value = assigned;
        vehicleSelect.dispatchEvent(new Event("change"));
      }
    });
    vehicleSelect.addEventListener("change", () => {
      const userTyped = odometer.value.trim() !== "" && odometer.dataset.auto !== "1";
      if (!isNew || userTyped) return;
      const vehicle = (lists.vehicles ?? []).find((item) => item.id === vehicleSelect.value);
      const lastClosed = pv.records
        .filter((record) => record.values.vehicle_id === vehicleSelect.value && record.values.odometer_in !== null)
        .sort((a, b) => b.values.odometer_in - a.values.odometer_in)[0];
      const start = lastClosed?.values.odometer_in ?? vehicle?.values.odometer_km;
      if (start !== undefined && start !== null) {
        odometer.value = String(start);
        odometer.dataset.auto = "1";
      }
    });
    odometer.addEventListener("input", () => delete odometer.dataset.auto);
  }

  if (entity.kind === "fuel") {
    const waybillSelect = field("waybill_id");
    waybillSelect.addEventListener("change", () => {
      const waybill = (lists.waybills ?? []).find((item) => item.id === waybillSelect.value);
      if (waybill && isNew) field("date").value = waybill.values.date;
      pvRenderFuelPreview(waybill);
    });
  }
}

function pvRenderWarnings(warnings) {
  const box = pvById("record-warnings");
  box.replaceChildren(
    ...warnings.map((text) => {
      const p = document.createElement("p");
      p.textContent = `⚠ ${text}`;
      return p;
    }),
  );
  box.hidden = !warnings.length;
}

function pvAddDetail(list, label, value, className = "") {
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.textContent = value;
  if (className) dd.className = className;
  list.append(dt, dd);
}

function pvRenderDetails(entity, record) {
  const list = pvById("record-details");
  list.replaceChildren();
  if (record && entity.details.length) {
    for (const detail of entity.details) {
      const raw = record.computed[detail.key];
      const isNumber = typeof raw === "number";
      const text = raw === null || raw === undefined ? "—" : isNumber ? pvFormatValue("number", raw, detail.unit) : String(raw);
      pvAddDetail(list, detail.label, text, detail.key === "deviation" && isNumber && raw > 0 ? "bad" : "");
    }
  }
  list.hidden = !list.childElementCount;
  if (entity.kind === "fuel") {
    const waybillId = pvById("f-waybill_id").value;
    const waybill = (pv.editing.lists.waybills ?? []).find((item) => item.id === waybillId);
    if (!record && waybill) pvRenderFuelPreview(waybill);
  }
}

/** While filling a fuel record, show whose card and car the chosen waybill brings in. */
function pvRenderFuelPreview(waybill) {
  const list = pvById("record-details");
  list.replaceChildren();
  if (!waybill) {
    list.hidden = true;
    return;
  }
  const card = waybill.computed.driver_card;
  pvAddDetail(list, "Водитель", waybill.labels.driver_id ?? "—");
  pvAddDetail(list, "Машина", waybill.labels.vehicle_id ?? "—");
  pvAddDetail(list, "Топливная карта", card, card === "—" ? "bad" : "");
  list.hidden = false;
  pvRenderWarnings(card === "—" ? ["У водителя не закреплена топливная карта — заправку сохранить нельзя."] : []);
}

function pvClearFormErrors() {
  pvById("record-error").hidden = true;
  for (const node of pvById("record-fields").querySelectorAll(".field-error")) {
    node.hidden = true;
    node.textContent = "";
  }
  for (const node of pvById("record-fields").querySelectorAll(".has-error")) node.classList.remove("has-error");
}

function pvShowFormError(error) {
  const summary = pvById("record-error");
  const detail = error instanceof ApiError ? error.detail : null;
  if (detail && typeof detail === "object" && detail.fields) {
    let first = null;
    for (const [name, message] of Object.entries(detail.fields)) {
      const slot = pvById(`e-${name}`);
      if (!slot) continue;
      slot.textContent = message;
      slot.hidden = false;
      slot.closest(".field").classList.add("has-error");
      first ??= pvById(`f-${name}`);
    }
    summary.textContent = detail.message ?? "Проверьте поля формы";
    summary.hidden = false;
    first?.focus();
    return;
  }
  summary.textContent = describeError(error);
  summary.hidden = false;
}

function pvCollect(entity) {
  const values = {};
  for (const field of entity.fields) {
    const element = pvById(`f-${field.name}`);
    values[field.name] = field.type === "bool" ? element.checked : element.value;
  }
  return values;
}

async function pvSubmit(event) {
  event.preventDefault();
  const { entity, record } = pv.editing;
  const button = pvById("record-save");
  pvClearFormErrors();
  button.disabled = true;
  try {
    const body = pvCollect(entity);
    const path = `/api/primavtodor/records/${entity.kind}`;
    if (record) await api("PUT", `${path}/${record.id}`, { body });
    else await api("POST", path, { body });
    pvById("dlg-record").close("saved");
    toast(record ? "Изменения сохранены" : "Запись создана");
    await pvLoadEntity();
  } catch (error) {
    pvShowFormError(error);
  } finally {
    button.disabled = false;
  }
}

/* ---------- fuel-card statement import ---------- */

function pvOpenImport() {
  pvById("import-file").value = "";
  pvById("import-summary").hidden = true;
  pvById("import-problems").hidden = true;
  pvById("import-error").hidden = true;
  pvById("import-apply").disabled = true;
  pvById("dlg-import").showModal();
}

async function pvSendStatement(file, apply) {
  const query = new URLSearchParams({ filename: file.name, apply: String(apply) });
  const response = await fetch(`/api/primavtodor/fuel/import?${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: await file.arrayBuffer(),
    cache: "no-store",
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    /* not JSON */
  }
  if (!response.ok) throw new ApiError(response.status, payload?.detail);
  return payload;
}

function pvRenderImport(report) {
  const counts = report.counts;
  const summary = pvById("import-summary");
  const parts = [`${report.period || "Выписка"}: операций ${counts.total}`];
  if (report.applied) parts.push(`загружено ${counts.new}`);
  else parts.push(`будет загружено ${counts.new} (${PV_UTIL.formatNumber(report.liters_new)} л)`);
  parts.push(`уже были ${counts.duplicate}`);
  if (counts.unmatched + counts.failed) parts.push(`не удалось привязать ${counts.unmatched + counts.failed}`);
  summary.textContent = parts.join(" · ");
  summary.hidden = false;

  const problems = report.operations.filter((op) => op.status === "unmatched" || op.status === "failed");
  const list = pvById("import-problems");
  list.replaceChildren(
    ...problems.map((op) => {
      const item = document.createElement("li");
      const when = `${PV_UTIL.formatDate(op.date)} ${op.time}`.trim();
      item.textContent = `${when} · ${PV_UTIL.formatNumber(op.liters)} л · ${op.reason}`;
      return item;
    }),
  );
  list.hidden = problems.length === 0;
}

async function pvPreviewImport() {
  const file = pvById("import-file").files[0];
  const apply = pvById("import-apply");
  apply.disabled = true;
  pvById("import-error").hidden = true;
  if (!file) return;
  try {
    const report = await pvSendStatement(file, false);
    pvRenderImport(report);
    apply.disabled = report.counts.new === 0;
    apply.textContent = report.counts.new ? `Загрузить: ${report.counts.new}` : "Загрузить";
  } catch (error) {
    pvById("import-summary").hidden = true;
    pvById("import-problems").hidden = true;
    const slot = pvById("import-error");
    slot.textContent = describeError(error);
    slot.hidden = false;
  }
}

async function pvApplyImport(event) {
  event.preventDefault();
  const file = pvById("import-file").files[0];
  const button = pvById("import-apply");
  if (!file) return;
  button.disabled = true;
  try {
    const report = await pvSendStatement(file, true);
    pvRenderImport(report);
    toast(`Загружено заправок: ${report.counts.new}`);
    await pvLoadEntity();
  } catch (error) {
    const slot = pvById("import-error");
    slot.textContent = describeError(error);
    slot.hidden = false;
    button.disabled = false; // some fill-ups may already be loaded; a retry only adds the rest
  }
}

/* ---------- closing the month ---------- */

const PV_STATUS_LABELS = { ok: "готово", warn: "проверить", error: "ошибка", info: "нет данных" };
const PV_SEVERITY_LABELS = { error: "Ошибка", warn: "Проверить", info: "К сведению" };

function pvOpenMonth() {
  const input = pvById("month-input");
  if (!input.value) input.value = pv.month ?? PV_UTIL.currentMonth();
  pvById("month-error").hidden = true;
  pvById("dlg-month").showModal();
  void pvLoadMonth();
}

function pvShiftReview(delta) {
  const input = pvById("month-input");
  input.value = PV_UTIL.shiftMonth(input.value || PV_UTIL.currentMonth(), delta);
  void pvLoadMonth();
}

async function pvLoadMonth() {
  const month = pvById("month-input").value;
  const error = pvById("month-error");
  error.hidden = true;
  if (!/^\d{4}-\d{2}$/.test(month)) return;
  try {
    const query = new URLSearchParams({ show_dismissed: String(pvById("month-show-dismissed").checked) });
    pvRenderMonth(await api("GET", `/api/primavtodor/month/${month}/review?${query}`));
  } catch (failure) {
    error.textContent = describeError(failure);
    error.hidden = false;
  }
}

function pvRenderMonth(review) {
  pvById("month-steps").replaceChildren(
    ...review.steps.map((step) => {
      const item = document.createElement("li");
      item.className = `month-step ${step.status}`;
      const badge = document.createElement("span");
      badge.className = "month-badge";
      badge.textContent = PV_STATUS_LABELS[step.status] ?? step.status;
      const text = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = step.title;
      const detail = document.createElement("small");
      detail.textContent = step.detail;
      text.append(title, detail);
      item.append(badge, text);
      return item;
    }),
  );

  const list = pvById("month-findings");
  list.replaceChildren(
    ...review.findings.map((finding) => {
      const item = document.createElement("li");
      item.className = `month-finding ${finding.severity}${finding.dismissed ? " dismissed" : ""}`;
      const head = document.createElement("div");
      const badge = document.createElement("span");
      badge.className = "month-badge";
      badge.textContent = PV_SEVERITY_LABELS[finding.severity] ?? finding.severity;
      const title = document.createElement("strong");
      title.textContent = finding.title;
      head.append(badge, title);
      const detail = document.createElement("small");
      detail.textContent = `${PV_UTIL.formatDate(finding.date)} · ${finding.subject} — ${finding.detail}`;
      const actions = document.createElement("div");
      actions.className = "month-actions";
      const open = document.createElement("button");
      open.type = "button";
      open.className = "btn btn-small";
      open.textContent = finding.kind === "fuel" ? "К заправкам" : "К путевым листам";
      open.addEventListener("click", () => {
        pvById("dlg-month").close();
        navigate({ module: PV_MODULE, section: finding.kind === "fuel" ? "fuel" : "waybills" });
      });
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "btn btn-small";
      toggle.textContent = finding.dismissed ? "Вернуть" : "Принять";
      toggle.title = finding.dismissed ? "Снова считать замечанием" : "Я посмотрел, так и должно быть";
      toggle.addEventListener("click", () => void pvToggleFinding(finding, toggle));
      actions.append(open, toggle);
      item.append(head, detail, actions);
      return item;
    }),
  );
  pvById("month-findings-title").hidden = review.findings.length === 0;
}

async function pvToggleFinding(finding, button) {
  button.disabled = true;
  try {
    const action = finding.dismissed ? "restore" : "dismiss";
    await api("POST", `/api/primavtodor/findings/${action}`, { body: { id: finding.id } });
    await pvLoadMonth();
  } catch (error) {
    const slot = pvById("month-error");
    slot.textContent = describeError(error);
    slot.hidden = false;
    button.disabled = false;
  }
}

async function pvDownloadPackage() {
  const button = pvById("month-package");
  button.disabled = true;
  try {
    const name = await pvDownload(`/api/primavtodor/month/${pvById("month-input").value}/package`);
    toast(`Пакет сохранён: ${name}`);
  } catch (error) {
    const slot = pvById("month-error");
    slot.textContent = describeError(error);
    slot.hidden = false;
  } finally {
    button.disabled = false;
  }
}

/* ---------- timesheet form and production calendar ---------- */

async function pvExportTimesheet() {
  const button = pvById("ts-export");
  button.disabled = true;
  try {
    const query = new URLSearchParams({ month: pv.month });
    const name = await pvDownload(`/api/primavtodor/timesheet/form?${query}`);
    toast(`Табель сохранён: ${name}`);
  } catch (error) {
    toast(`Не удалось сформировать табель: ${describeError(error)}`, "error");
  } finally {
    button.disabled = false;
  }
}

const PV_MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];

async function pvOpenCalendar() {
  const error = pvById("cal-error");
  error.hidden = true;
  try {
    const info = await api("GET", "/api/primavtodor/calendar");
    const select = pvById("cal-year");
    const wanted = Number.parseInt(pv.month?.slice(0, 4) ?? "", 10);
    select.replaceChildren(...info.years.map((year) => new Option(String(year), String(year))));
    select.value = String(info.years.includes(wanted) ? wanted : info.years[0]);
    pvById("cal-legend").replaceChildren(
      ...Object.entries(info.labels).map(([kind, label]) => {
        const span = document.createElement("span");
        const swatch = document.createElement("i");
        swatch.className = `cal-day ${kind}`;
        span.append(swatch, label);
        return span;
      }),
    );
    pvById("dlg-calendar").showModal();
    await pvShowCalendarYear();
  } catch (failure) {
    toast(`Не удалось открыть календарь: ${describeError(failure)}`, "error");
  }
}

async function pvShowCalendarYear() {
  const year = pvById("cal-year").value;
  const error = pvById("cal-error");
  error.hidden = true;
  try {
    const view = await api("GET", `/api/primavtodor/calendar/${year}`);
    pvById("cal-total").textContent = `${view.workdays} рабочих дней, ${view.hours} ч (40-часовая неделя)`;
    pvById("cal-grid").replaceChildren(
      ...view.months.map((month) => {
        const box = document.createElement("section");
        box.className = "cal-month";
        const title = document.createElement("h3");
        title.textContent = PV_MONTHS[month.month - 1];
        const norm = document.createElement("small");
        norm.textContent = `${month.norm.workdays} дн. · ${month.norm.hours} ч`;
        const days = document.createElement("div");
        days.className = "cal-days";
        for (let i = 0; i < month.days[0].weekday; i += 1) days.append(document.createElement("span"));
        for (const day of month.days) {
          const cell = document.createElement("span");
          cell.className = `cal-day ${day.kind}${day.holiday ? " holiday" : ""}${day.transferred ? " moved" : ""}`;
          cell.textContent = String(day.day);
          if (day.transferred) cell.title = "Выходной по переносу";
          else if (day.holiday) cell.title = "Праздничный день";
          else if (day.kind === "short") cell.title = "Сокращённый день";
          days.append(cell);
        }
        box.append(title, norm, days);
        return box;
      }),
    );
  } catch (failure) {
    error.textContent = describeError(failure);
    error.hidden = false;
  }
}

/* ---------- monthly fuel analysis ---------- */

function pvOpenReport() {
  if (!pvById("report-month").value) pvById("report-month").value = PV_UTIL.currentMonth();
  pvById("report-error").hidden = true;
  pvById("dlg-report").showModal();
}

async function pvDownloadReport(event) {
  event.preventDefault();
  const month = pvById("report-month").value;
  const slot = pvById("report-error");
  slot.hidden = true;
  if (!/^\d{4}-\d{2}$/.test(month)) {
    slot.textContent = "Выберите месяц";
    slot.hidden = false;
    return;
  }
  const button = pvById("report-download");
  button.disabled = true;
  try {
    const name = await pvDownload(`/api/primavtodor/reports/fuel?${new URLSearchParams({ month })}`);
    toast(`Отчёт сохранён: ${name}`);
  } catch (error) {
    slot.textContent = describeError(error);
    slot.hidden = false;
  } finally {
    button.disabled = false;
  }
}

/* ---------- printing ---------- */

/** Download a generated file; failures come back as a readable message, not a saved error page. */
async function pvDownload(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    let detail = null;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, detail);
  }
  const match = /filename\*=UTF-8''([^;]+)/i.exec(response.headers.get("Content-Disposition") ?? "");
  let name = "файл.xlsx";
  try {
    if (match) name = decodeURIComponent(match[1]);
  } catch {
    /* keep the default name */
  }
  const url = URL.createObjectURL(await response.blob());
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return name;
}

async function pvPrintWaybill() {
  const { record } = pv.editing ?? {};
  if (!record) return;
  const button = pvById("record-print");
  button.disabled = true;
  try {
    const name = await pvDownload(`/api/primavtodor/waybills/${encodeURIComponent(record.id)}/print`);
    toast(`Бланк сохранён: ${name}`);
  } catch (error) {
    pvShowFormError(error);
  } finally {
    button.disabled = false;
  }
}

async function pvDownloadFuelCard() {
  const { record } = pv.editing ?? {};
  const month = pvById("card-month").value;
  if (!record) return;
  if (!/^\d{4}-\d{2}$/.test(month)) {
    pvShowFormError(new Error("Выберите месяц"));
    return;
  }
  const button = pvById("card-download");
  button.disabled = true;
  try {
    const query = new URLSearchParams({ month });
    const name = await pvDownload(`/api/primavtodor/vehicles/${encodeURIComponent(record.id)}/fuel-card?${query}`);
    toast(`Карточка сохранена: ${name}`);
  } catch (error) {
    pvShowFormError(error);
  } finally {
    button.disabled = false;
  }
}

async function pvOpenPrintSettings() {
  let data;
  try {
    data = await api("GET", "/api/primavtodor/settings/print");
  } catch (error) {
    toast(`Не удалось открыть настройки: ${describeError(error)}`, "error");
    return;
  }
  const box = pvById("print-fields");
  const wrap = (id, caption, control) => {
    const wrapper = document.createElement("div");
    wrapper.className = "field";
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = caption;
    wrapper.append(label, control);
    return wrapper;
  };
  const rows = data.fields.map((field) => {
    const input = document.createElement(field.key === "org_header" ? "textarea" : "input");
    input.id = `pf-${field.key}`;
    input.name = field.key;
    input.value = data.values[field.key] ?? "";
    if (input.tagName === "TEXTAREA") input.rows = 3;
    else input.type = "text";
    const wrapper = wrap(input.id, field.label, input);
    if (field.key === "org_header") wrapper.classList.add("span-2");
    return wrapper;
  });
  const select = document.createElement("select");
  select.id = "pf-control";
  select.name = "control";
  for (const option of data.control_options) {
    select.append(new Option(option.label, option.value, false, option.value === data.values.control));
  }
  box.replaceChildren(...rows, wrap("pf-control", "Кто разрешает выезд", select));
  pvById("print-error").hidden = true;
  pvById("dlg-print").showModal();
  box.querySelector("input, textarea")?.focus();
}

async function pvSavePrintSettings(event) {
  event.preventDefault();
  const button = pvById("print-save");
  button.disabled = true;
  try {
    const body = {};
    for (const input of pvById("print-fields").querySelectorAll("input, textarea, select")) {
      body[input.name] = input.value;
    }
    await api("PUT", "/api/primavtodor/settings/print", { body });
    pvById("dlg-print").close("saved");
    toast("Данные для печати сохранены");
  } catch (error) {
    const slot = pvById("print-error");
    slot.textContent = describeError(error);
    slot.hidden = false;
  } finally {
    button.disabled = false;
  }
}

async function pvDelete() {
  const { entity, record } = pv.editing;
  const confirmed = await askConfirm({
    title: "Удалить запись?",
    text: `«${record.label}» будет удалена без возможности восстановления.`,
    okLabel: "Удалить",
  });
  if (!confirmed) return;
  try {
    await api("DELETE", `/api/primavtodor/records/${entity.kind}/${record.id}`);
    pvById("dlg-record").close("deleted");
    toast("Запись удалена");
    await pvLoadEntity();
  } catch (error) {
    pvShowFormError(error);
  }
}

/* ---------- timesheet ---------- */

function pvSetMonth(month) {
  pv.month = month;
  void pvLoadTimesheet();
}

function pvShiftMonth(delta) {
  pvSetMonth(PV_UTIL.shiftMonth(pv.month ?? PV_UTIL.currentMonth(), delta));
}

async function pvLoadTimesheet() {
  pv.month ??= PV_UTIL.currentMonth();
  pvById("ts-month").value = pv.month;
  pv.tsController?.abort();
  const controller = new AbortController();
  pv.tsController = controller;
  const month = pv.month;
  try {
    const data = await api("GET", "/api/primavtodor/timesheet", { params: { month }, signal: controller.signal });
    if (controller.signal.aborted || month !== pv.month) return;
    pv.timesheet = data;
    pvRenderTimesheet(data);
  } catch (error) {
    if (isAbort(error) || month !== pv.month) return;
    pvById("ts-table").replaceChildren();
    pvShowEmpty("ts-empty", "Не удалось загрузить табель", describeError(error), "Повторить", () => void pvLoadTimesheet());
  }
}

function pvCodeBadge(code) {
  const span = document.createElement("span");
  span.className = `ts-code code-${code}`;
  span.textContent = code;
  return span;
}

function pvRenderNorm(norm) {
  const text = norm.from_calendar
    ? `Норма месяца по производственному календарю: ${norm.workdays} раб. дн., ${norm.hours} ч` +
      (norm.short_days ? ` (сокращённых дней: ${norm.short_days})` : "")
    : "Календаря на этот год в программе нет: выходными считаются суббота и воскресенье.";
  pvById("ts-norm").textContent = text;
}

function pvRenderTimesheet(data) {
  pvRenderNorm(data.norm);
  const legend = pvById("ts-legend");
  legend.replaceChildren(
    ...data.codes.map((item) => {
      const span = document.createElement("span");
      span.append(pvCodeBadge(item.code), item.label);
      return span;
    }),
  );

  const table = pvById("ts-table");
  const head = document.createElement("tr");
  const who = document.createElement("th");
  who.className = "who";
  who.scope = "col";
  who.textContent = "Сотрудник";
  head.append(who);
  for (const day of data.days) {
    const th = document.createElement("th");
    th.scope = "col";
    if (day.off) th.className = "weekend";
    if (day.kind === "short") th.title = "Сокращённый день (на час короче)";
    th.append(String(day.day));
    const small = document.createElement("small");
    small.textContent = PV_WEEKDAYS[day.weekday];
    th.append(small);
    head.append(th);
  }
  for (const label of ["Я", "Путевых", "Км"]) {
    const th = document.createElement("th");
    th.className = "total";
    th.scope = "col";
    th.textContent = label;
    head.append(th);
  }

  const codeLabels = Object.fromEntries(data.codes.map((item) => [item.code, item.label]));
  const body = document.createElement("tbody");
  for (const row of data.rows) {
    const tr = document.createElement("tr");
    const name = document.createElement("th");
    name.className = "who";
    name.scope = "row";
    name.textContent = row.name;
    if (row.position) {
      const small = document.createElement("small");
      small.textContent = row.personnel_number ? `${row.position} · № ${row.personnel_number}` : row.position;
      name.append(small);
    }
    tr.append(name);

    row.cells.forEach((cell, index) => {
      const td = document.createElement("td");
      if (data.days[index].off) td.className = "weekend";
      const button = document.createElement("button");
      button.type = "button";
      button.className = `ts-cell${cell.source === "manual" ? " manual" : ""}${cell.conflict ? " conflict" : ""}`;
      const meaning = cell.code ? codeLabels[cell.code] : "нет отметки";
      button.setAttribute("aria-label", `${row.name}, ${PV_UTIL.formatDate(cell.date)}: ${meaning}`);
      const hint = [meaning];
      if (cell.source === "waybill") hint.push("по путевому листу");
      if (cell.source === "manual") hint.push("вручную");
      if (cell.conflict) hint.push("на этот день есть путевой лист");
      button.title = hint.join(" · ");
      if (cell.code) {
        button.append(pvCodeBadge(cell.code));
      } else {
        const dot = document.createElement("span");
        dot.className = "dot";
        dot.textContent = "·";
        button.append(dot);
      }
      button.addEventListener("click", () => pvOpenMark(row, cell));
      td.append(button);
      tr.append(td);
    });

    for (const value of [row.totals.worked, row.totals.waybills, row.totals.distance]) {
      const td = document.createElement("td");
      td.className = "total";
      td.textContent = PV_UTIL.formatNumber(value);
      tr.append(td);
    }
    body.append(tr);
  }

  const thead = document.createElement("thead");
  thead.append(head);
  table.replaceChildren(thead, body);

  const empty = pvById("ts-empty");
  if (!data.rows.length) {
    pvShowEmpty(
      "ts-empty",
      "В табеле пока никого нет",
      "Сотрудники появятся здесь, когда вы добавите их в разделе «Сотрудники».",
      "Открыть сотрудников",
      () => navigate({ module: PV_MODULE, section: "employees" }),
    );
  } else {
    empty.hidden = true;
  }
}

function pvOpenMark(row, cell) {
  pv.mark = { row, cell };
  pvById("mark-note").textContent = `${row.name} · ${PV_UTIL.formatDate(cell.date)}${
    cell.source === "waybill" ? " (есть путевой лист)" : ""
  }`;
  pvById("mark-error").hidden = true;
  const select = pvById("mark-code");
  select.replaceChildren();
  const auto = document.createElement("option");
  auto.value = "";
  auto.textContent = "— автоматически (по путевым листам) —";
  select.append(auto);
  for (const item of pv.timesheet.codes) {
    const option = document.createElement("option");
    option.value = item.code;
    option.textContent = `${item.code} — ${item.label}`;
    select.append(option);
  }
  select.value = cell.source === "manual" ? cell.code : "";
  pvById("dlg-mark").returnValue = "";
  pvById("dlg-mark").showModal();
  select.focus();
}

async function pvSubmitMark(event) {
  event.preventDefault();
  const { row, cell } = pv.mark;
  const button = pvById("mark-save");
  button.disabled = true;
  try {
    await api("PUT", "/api/primavtodor/timesheet/mark", {
      body: {
        month: pv.month,
        employee_id: row.employee_id,
        date: cell.date,
        code: pvById("mark-code").value || null,
      },
    });
    pvById("dlg-mark").close("saved");
    toast("Отметка сохранена");
    await pvLoadTimesheet();
  } catch (error) {
    const slot = pvById("mark-error");
    slot.textContent = describeError(error);
    slot.hidden = false;
  } finally {
    button.disabled = false;
  }
}
