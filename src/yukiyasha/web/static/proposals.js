"use strict";

/* Pure proposal review helpers; shared by the browser UI and Node tests. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.YukiProposal = api;
})(typeof self !== "undefined" ? self : globalThis, function () {
  const FIELD_LABELS = {
    plate: "Госномер",
    model: "Модель",
    active: "Активна",
    fuel_type: "Топливо",
    norm_summer: "Летняя норма",
    norm_winter: "Зимняя норма",
    odometer_km: "Одометр",
    full_name: "ФИО",
    personnel_number: "Табельный номер",
    phone: "Телефон",
    fuel_card_number: "Топливная карта",
    vehicle_id: "Машина",
    driver_id: "Водитель",
    waybill_id: "Путевой лист",
    number: "Номер",
    date: "Дата",
    date_from: "Дата начала",
    date_to: "Дата окончания",
    route: "Маршрут",
    distance_km: "Пробег",
    fuel_liters: "Топливо, л",
    season: "Сезон",
    status: "Статус",
  };

  const STATUS_LABELS = {
    pending: "Ожидает подтверждения",
    applied: "Применено",
    rejected: "Отклонено",
    stale: "Устарело",
  };

  const OPERATION_LABELS = {
    create: "Создание",
    update: "Изменение",
    delete: "Удаление",
  };

  const KIND_LABELS = {
    vehicles: "Машины",
    employees: "Сотрудники",
    waybills: "Путевые листы",
    fuel: "ГСМ",
  };

  function equalValue(left, right) {
    return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
  }

  function buildProposalDiff(proposal) {
    const operation = proposal?.operation;
    const before = proposal?.before && typeof proposal.before === "object"
      ? proposal.before
      : {};
    const after = proposal?.payload && typeof proposal.payload === "object"
      ? proposal.payload
      : {};
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();

    if (operation === "create") {
      return keys.map((field) => ({ field, before: null, after: after[field], change: "add" }));
    }
    if (operation === "delete") {
      return keys.map((field) => ({ field, before: before[field], after: null, change: "remove" }));
    }
    return keys
      .filter((field) => !equalValue(before[field], after[field]))
      .map((field) => ({
        field,
        before: before[field],
        after: after[field],
        change: "update",
      }));
  }

  function fieldLabel(field) {
    return FIELD_LABELS[field] ?? field.replaceAll("_", " ");
  }

  function statusLabel(status) {
    return STATUS_LABELS[status] ?? status ?? "—";
  }

  function operationLabel(operation) {
    return OPERATION_LABELS[operation] ?? operation ?? "—";
  }

  function kindLabel(kind) {
    return KIND_LABELS[kind] ?? kind ?? "—";
  }

  function formatValue(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "Да" : "Нет";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  return {
    buildProposalDiff,
    fieldLabel,
    statusLabel,
    operationLabel,
    kindLabel,
    formatValue,
  };
});
