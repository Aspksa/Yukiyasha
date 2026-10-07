"use strict";

/* График машин: a car × day grid on the Примавтодор page. Records live in /api/primavtodor/bookings. */

const SCH_KIND_ICON = { trip: "➜", busy: "●", service: "⚙" };
const SCH_WEEKDAYS = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
const SCH_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

const sch = {
  wired: false,
  start: null, // Date at local midnight
  days: 14,
  data: null,
  drag: null, // { vehicleId, from, to, track }
  editing: null,
  kind: "trip",
  employees: [],
  controller: null,
};

const schById = (id) => document.getElementById(id);

function schIso(date) {
  return PV_UTIL.todayIso(date);
}

function schParse(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function schAdd(date, n) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + n);
}

function schDiff(aIso, bIso) {
  return Math.round((schParse(aIso) - schParse(bIso)) / 86400000);
}

function schEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** "Веровский Иван Петрович" -> "Веровский И." */
function schShort(name) {
  const [last, first] = String(name || "").trim().split(/\s+/);
  return first ? `${last} ${first[0]}.` : last || "";
}

function schDayLabel(iso) {
  const date = schParse(iso);
  return `${date.getDate()} ${SCH_MONTHS[date.getMonth()]}`;
}

function schWire() {
  if (sch.wired) return;
  sch.wired = true;
  const today = new Date();
  sch.start = schAdd(new Date(today.getFullYear(), today.getMonth(), today.getDate()), -1);

  schById("sch-prev").addEventListener("click", () => schShift(-Math.floor(sch.days / 2)));
  schById("sch-next").addEventListener("click", () => schShift(Math.floor(sch.days / 2)));
  schById("sch-today").addEventListener("click", () => {
    const now = new Date();
    sch.start = schAdd(new Date(now.getFullYear(), now.getMonth(), now.getDate()), -1);
    void schLoad();
  });
  for (const button of document.querySelectorAll(".sch-span [data-days]")) {
    button.addEventListener("click", () => {
      sch.days = Number(button.dataset.days);
      void schLoad();
    });
  }
  schById("sch-new").addEventListener("click", () => void schOpen({ from: schIso(new Date()) }));
  schById("form-booking").addEventListener("submit", (event) => void schSave(event));
  schById("bk-delete").addEventListener("click", () => void schDelete());
  for (const id of ["bk-from", "bk-to"]) schById(id).addEventListener("change", () => void schFree());
  schById("bk-driver").addEventListener("change", schSuggestVehicle);
  schById("bk-vehicle").addEventListener("change", schSuggestDriver);
  document.addEventListener("pointerup", schEndDrag);
}

function schShift(days) {
  sch.start = schAdd(sch.start, days);
  void schLoad();
}

async function schLoad() {
  schWire();
  sch.controller?.abort();
  const controller = new AbortController();
  sch.controller = controller;
  for (const button of document.querySelectorAll(".sch-span [data-days]")) {
    button.classList.toggle("active", Number(button.dataset.days) === sch.days);
  }
  try {
    const params = { start: schIso(sch.start), days: sch.days };
    sch.data = await api("GET", "/api/primavtodor/bookings", { params, signal: controller.signal });
    if (controller.signal.aborted) return;
    schRender();
  } catch (error) {
    if (isAbort(error)) return;
    const box = schEl("div", "module-error");
    box.append(schEl("strong", "", "График не загрузился"), document.createElement("br"), describeError(error));
    schById("sch-grid").replaceChildren(box);
  }
}

/* ---------- rendering ---------- */

function schRender() {
  const data = sch.data;
  schById("sch-range").textContent = `${schDayLabel(data.start)} — ${schDayLabel(data.end)}`;
  schRenderNow(data);
  const grid = schById("sch-grid");
  grid.style.setProperty("--days", data.days.length);

  const head = schEl("div", "sch-row sch-headrow");
  head.append(schEl("div", "sch-car sch-corner", "Машина"));
  const days = schEl("div", "sch-days");
  data.days.forEach((day, index) => {
    const date = schParse(day.date);
    const cell = schEl("div", `sch-day ${day.kind}${day.date === data.today ? " today" : ""}`);
    if (index === 0 || date.getDate() === 1) {
      cell.append(schEl("span", "sch-month", SCH_MONTHS[date.getMonth()].slice(0, 3)));
    }
    cell.append(schEl("b", "", String(date.getDate())), schEl("small", "", SCH_WEEKDAYS[date.getDay()]));
    days.append(cell);
  });
  head.append(days);

  const rows = data.vehicles.map((vehicle) => schRenderCar(vehicle, data));
  if (!rows.length) {
    const empty = schEl("p", "sch-empty", "Добавьте машины в разделе «Гараж» — они появятся здесь.");
    grid.replaceChildren(head, empty);
    return;
  }
  grid.replaceChildren(head, ...rows);
}

function schRenderNow(data) {
  const box = schById("sch-now");
  const parts = [];
  const chip = (row, soon) => {
    const left = schDiff(row.date_to, data.today) + 1;
    const node = schEl("button", `sch-chip ${row.kind}${soon ? " soon" : ""}`);
    node.type = "button";
    node.append(
      schEl("span", "sch-chip-icon", SCH_KIND_ICON[row.kind] ?? "●"),
      schEl("b", "", row.vehicle),
      schEl("span", "", row.driver ? schShort(row.driver) : row.kind_label),
    );
    const when = soon
      ? `с ${schDayLabel(row.date_from)}`
      : left <= 1
        ? "до сегодня"
        : `ещё ${left} ${plural(left, "день", "дня", "дней")} · до ${PV_UTIL.formatDate(row.date_to).slice(0, 5)}`;
    node.append(schEl("em", "", when));
    node.title = `${row.kind_label}${row.note ? ` · ${row.note}` : ""} · ${row.span}`;
    node.addEventListener("click", () => void schOpen({ id: row.id }));
    return node;
  };
  if (data.now.length) {
    parts.push(schEl("span", "sch-now-label", "Сейчас в отъезде"), ...data.now.map((row) => chip(row, false)));
  } else {
    parts.push(schEl("span", "sch-now-label ok", "Сегодня все машины на месте"));
  }
  if (data.soon.length) {
    parts.push(schEl("span", "sch-now-label", "Скоро"), ...data.soon.map((row) => chip(row, true)));
  }
  box.replaceChildren(...parts);
}

function schLanes(rows) {
  const ends = [];
  const placed = [];
  for (const row of rows) {
    let lane = ends.findIndex((end) => end < row.date_from);
    if (lane < 0) {
      lane = ends.length;
      ends.push("");
    }
    ends[lane] = row.date_to;
    placed.push({ row, lane });
  }
  return { placed, count: Math.max(1, ends.length) };
}

function schRenderCar(vehicle, data) {
  const mine = data.bookings.filter((row) => row.vehicle_id === vehicle.id);
  const { placed, count } = schLanes(mine);
  const total = data.days.length;

  const row = schEl("div", "sch-row");
  const car = schEl("div", "sch-car");
  car.append(schEl("b", "mono", vehicle.plate), schEl("span", "", vehicle.model));
  if (vehicle.driver) car.append(schEl("small", "", `обычно ${schShort(vehicle.driver)}`));

  const track = schEl("div", "sch-track");
  track.style.setProperty("--lanes", count);
  const cells = schEl("div", "sch-cells");
  data.days.forEach((day, index) => {
    const cell = schEl("div", `sch-cell ${day.kind}${day.date === data.today ? " today" : ""}`);
    cell.dataset.i = String(index);
    cell.addEventListener("pointerdown", (event) => schStartDrag(event, vehicle.id, index, track));
    cell.addEventListener("pointerenter", () => schMoveDrag(vehicle.id, index));
    cells.append(cell);
  });
  const bars = schEl("div", "sch-bars");
  for (const { row: booking, lane } of placed) {
    const from = Math.max(0, schDiff(booking.date_from, data.start));
    const to = Math.min(total - 1, schDiff(booking.date_to, data.start));
    const bar = schEl("button", `sch-bar ${booking.kind}${booking.conflicts.length ? " clash" : ""}`);
    bar.type = "button";
    bar.style.gridColumn = `${from + 1} / ${to + 2}`;
    bar.style.gridRow = String(lane + 1);
    if (booking.date_from < data.start) bar.classList.add("cut-left");
    if (booking.date_to > data.end) bar.classList.add("cut-right");
    bar.append(schEl("span", "sch-bar-icon", SCH_KIND_ICON[booking.kind] ?? "●"));
    bar.append(schEl("span", "sch-bar-text", booking.driver ? schShort(booking.driver) : booking.kind_label));
    if (booking.note && to - from >= 2) bar.append(schEl("small", "", booking.note));
    const warn = booking.conflicts.length ? `\n⚠ ${booking.conflicts.join("; ")}` : "";
    bar.title = `${booking.kind_label}: ${booking.driver || booking.vehicle}\n${booking.span} · ${booking.days} ${plural(booking.days, "день", "дня", "дней")}${booking.note ? `\n${booking.note}` : ""}${warn}`;
    bar.addEventListener("click", () => void schOpen({ id: booking.id }));
    bars.append(bar);
  }
  track.append(cells, bars);
  row.append(car, track);
  return row;
}

/* ---------- drag to create ---------- */

function schStartDrag(event, vehicleId, index, track) {
  if (event.button !== 0) return;
  event.preventDefault();
  sch.drag = { vehicleId, from: index, to: index, track };
  schPaintDrag();
}

function schMoveDrag(vehicleId, index) {
  if (!sch.drag || sch.drag.vehicleId !== vehicleId) return;
  sch.drag.to = index;
  schPaintDrag();
}

function schPaintDrag() {
  const { from, to, track } = sch.drag;
  const [low, high] = from <= to ? [from, to] : [to, from];
  for (const cell of track.querySelectorAll(".sch-cell")) {
    const i = Number(cell.dataset.i);
    cell.classList.toggle("pick", i >= low && i <= high);
  }
}

function schEndDrag() {
  const drag = sch.drag;
  if (!drag) return;
  sch.drag = null;
  for (const cell of drag.track.querySelectorAll(".pick")) cell.classList.remove("pick");
  const [low, high] = drag.from <= drag.to ? [drag.from, drag.to] : [drag.to, drag.from];
  const day = (i) => schIso(schAdd(sch.start, i));
  void schOpen({ vehicle_id: drag.vehicleId, from: day(low), to: day(high) });
}

/* ---------- dialog ---------- */

function schFillSelect(select, options, selected, blank) {
  select.replaceChildren();
  if (blank) select.append(new Option(blank, ""));
  for (const [value, label] of options) select.append(new Option(label, value));
  select.value = selected ?? "";
}

async function schOpen({ id = null, vehicle_id = "", from = "", to = "" }) {
  const dialog = schById("dlg-booking");
  if (dialog.open) return;
  try {
    const employees = await api("GET", "/api/primavtodor/records/employees");
    sch.employees = employees.records.filter((item) => item.values.is_driver);
  } catch (error) {
    toast(describeError(error), "error");
    return;
  }
  const existing = id ? sch.data.bookings.find((row) => row.id === id) : null;
  if (id && !existing) {
    toast("Запись не найдена, обновите график", "error");
    return;
  }
  sch.editing = existing;
  const values = existing ?? { vehicle_id, driver_id: "", date_from: from, date_to: to || from, kind: "trip", note: "" };

  schById("dlg-booking-title").textContent = existing ? "Изменить выезд" : "Выезд машины";
  schFillSelect(
    schById("bk-vehicle"),
    sch.data.vehicles.map((car) => [car.id, `${car.plate} · ${car.model}`]),
    values.vehicle_id,
    "— выберите —",
  );
  schFillSelect(
    schById("bk-driver"),
    sch.employees.map((item) => [item.id, item.values.full_name]),
    values.driver_id ?? "",
    "— выберите —",
  );
  schById("bk-from").value = values.date_from;
  schById("bk-to").value = values.date_to;
  schById("bk-note").value = values.note ?? "";
  schSetKind(values.kind);
  schById("bk-delete").hidden = !existing;
  schById("bk-error").hidden = true;
  schShowErrors({});
  const warn = schById("bk-warn");
  warn.hidden = !existing?.conflicts.length;
  warn.replaceChildren(...(existing?.conflicts ?? []).map((text) => schEl("p", "", `⚠ ${text}`)));
  dialog.showModal();
  void schFree();
  if (!existing && !values.vehicle_id) schById("bk-driver").focus();
}

function schSetKind(kind) {
  sch.kind = kind;
  const box = schById("bk-kinds");
  box.replaceChildren(
    ...sch.data.kinds.map((item) => {
      const button = schEl("button", `sch-kind ${item.value}${item.value === kind ? " active" : ""}`);
      button.type = "button";
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", String(item.value === kind));
      button.append(schEl("span", "sch-kind-icon", SCH_KIND_ICON[item.value] ?? "●"), item.label);
      button.addEventListener("click", () => schSetKind(item.value));
      return button;
    }),
  );
}

function schSuggestVehicle() {
  const driver = sch.employees.find((item) => item.id === schById("bk-driver").value);
  const vehicle = schById("bk-vehicle");
  const assigned = driver?.values.vehicle_id;
  if (!vehicle.value && assigned && [...vehicle.options].some((o) => o.value === assigned)) {
    vehicle.value = assigned;
  }
}

function schSuggestDriver() {
  const driver = schById("bk-driver");
  if (driver.value) return;
  const match = sch.employees.find((item) => item.values.vehicle_id === schById("bk-vehicle").value);
  if (match) driver.value = match.id;
}

async function schFree() {
  const box = schById("bk-free");
  const from = schById("bk-from").value;
  const to = schById("bk-to").value || from;
  if (!from || to < from) {
    box.replaceChildren();
    return;
  }
  try {
    const result = await api("GET", "/api/primavtodor/bookings/free", { params: { from, to } });
    const label = schEl("span", "", result.vehicles.length ? "Свободны на эти дни:" : "На эти дни свободных машин нет");
    const chips = result.vehicles.map((car) => {
      const chip = schEl("button", "sch-free-chip mono", car.plate);
      chip.type = "button";
      chip.title = car.model;
      chip.addEventListener("click", () => {
        schById("bk-vehicle").value = car.id;
        schSuggestDriver();
      });
      return chip;
    });
    box.replaceChildren(label, ...chips);
  } catch {
    box.replaceChildren();
  }
}

function schShowErrors(fields) {
  for (const node of schById("form-booking").querySelectorAll("[data-err]")) {
    node.textContent = fields[node.dataset.err] ?? "";
  }
}

async function schSave(event) {
  event.preventDefault();
  const body = {
    kind: sch.kind,
    vehicle_id: schById("bk-vehicle").value,
    driver_id: schById("bk-driver").value,
    date_from: schById("bk-from").value,
    date_to: schById("bk-to").value,
    note: schById("bk-note").value,
  };
  const button = schById("bk-save");
  button.disabled = true;
  schById("bk-error").hidden = true;
  try {
    const saved = sch.editing
      ? await api("PUT", `/api/primavtodor/bookings/${sch.editing.id}`, { body })
      : await api("POST", "/api/primavtodor/bookings", { body });
    schById("dlg-booking").close("ok");
    if (saved.conflicts.length) toast(`Записано, но есть пересечение: ${saved.conflicts[0]}`, "error");
    else toast("Записано в график");
    await schLoad();
  } catch (error) {
    const fields = error instanceof ApiError ? error.detail?.fields : null;
    if (fields) schShowErrors(fields);
    const slot = schById("bk-error");
    slot.textContent = describeError(error);
    slot.hidden = false;
  } finally {
    button.disabled = false;
  }
}

async function schDelete() {
  if (!sch.editing) return;
  const ok = await askConfirm({
    title: "Убрать выезд из графика?",
    text: `${sch.editing.vehicle} · ${sch.editing.driver || sch.editing.kind_label} · ${sch.editing.span}`,
    okLabel: "Убрать",
  });
  if (!ok) return;
  try {
    await api("DELETE", `/api/primavtodor/bookings/${sch.editing.id}`);
    schById("dlg-booking").close("ok");
    toast("Убрано из графика");
    await schLoad();
  } catch (error) {
    const slot = schById("bk-error");
    slot.textContent = describeError(error);
    slot.hidden = false;
  }
}
