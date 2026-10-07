"""Quick booking from one line typed during a phone call: «Веровский 7-9 командировка Находка».

Pure parsing: drivers, cars and today's date come in, a guess with the reasons it could not be
complete comes out. Nothing is stored here and nothing is guessed silently: what is ambiguous is
listed as candidates for the person to pick.
"""

import calendar
import os.path
import re
from datetime import date, timedelta

LATIN_TO_CYR = str.maketrans("abekmhopctyx", "авекмнорстух")
RANGE_RE = re.compile(
    r"(?<![\d.])(?:с\s*)?(\d{1,2})(?:[./](\d{1,2}))?\s*(?:-|–|—|по|до)\s*(\d{1,2})(?:[./](\d{1,2}))?(?![\d])"
)
SINGLE_RE = re.compile(r"(?<![\d.])(\d{1,2})(?:[./](\d{1,2}))?(?![\d])")
KIND_WORDS = (
    ("service", re.compile(r"ремонт\w*|сервис\w*|обслужив\w*|\bто\b")),
    ("busy", re.compile(r"занят\w*|весь день|целый день|на день")),
    ("trip", re.compile(r"командиров\w*|\bком\b|выезд\w*|поездк\w*")),
)
STOP = {
    "в", "на", "с", "по", "до", "и", "дай", "дать", "машину", "машина", "едет", "поехал",
    "поедет", "нужна", "нужен", "надо", "число", "числа", "года", "из", "за", "для",
}  # fmt: skip
# how people say a make they usually see written in Latin letters
ALIASES = {
    "toyota": ("тойота",), "lexus": ("лексус",), "hino": ("хино",), "kia": ("киа",),
    "hyundai": ("хендай", "хундай", "хёндэ"), "nissan": ("ниссан",), "mazda": ("мазда",),
    "mitsubishi": ("митсубиси", "мицубиси"), "isuzu": ("исузу",), "ford": ("форд",),
    "volkswagen": ("фольксваген",), "renault": ("рено",), "skoda": ("шкода",),
    "land": ("ленд",), "cruiser": ("крузер",), "kamaz": ("камаз",), "man": ("ман",),
}  # fmt: skip
RELATIVE = {"сегодня": 0, "завтра": 1, "послезавтра": 2}


def _norm(text: object) -> str:
    return str(text or "").lower().replace("ё", "е")


def _plate_key(plate: object) -> str:
    return re.sub(r"[^0-9а-яa-z]", "", _norm(plate)).translate(LATIN_TO_CYR)


def _plate_regex(key: str) -> re.Pattern[str]:
    return re.compile(r"\s*".join(re.escape(ch) for ch in key))


def _month_add(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + delta
    return index // 12, index % 12 + 1


def _safe(year: int, month: int, day: int) -> date | None:
    year, month = _month_add(year, month, 0)
    if not 1 <= day <= calendar.monthrange(year, month)[1]:
        return None
    return date(year, month, day)


def _dates(text: str, today: date) -> tuple[date | None, date | None, str]:
    """Start and end dates found in ``text`` and the text without them."""
    for word, offset in RELATIVE.items():
        if re.search(rf"\b{word}\b", text):
            day = today + timedelta(days=offset)
            return day, day, re.sub(rf"\b{word}\b", " ", text, count=1)
    match = RANGE_RE.search(text)
    first_day, first_month, last_day, last_month = (
        (int(match[1]), match[2], int(match[3]), match[4]) if match else (0, None, 0, None)
    )
    if not match:
        match = SINGLE_RE.search(text)
        if not match:
            return None, None, text
        first_day, first_month = int(match[1]), match[2]
        last_day, last_month = first_day, first_month
    rest = text[: match.start()] + " " + text[match.end() :]

    if any(m and not 1 <= int(m) <= 12 for m in (first_month, last_month)):
        return None, None, rest
    month = int(first_month) if first_month else today.month
    start = _safe(today.year, month, first_day)
    if start is None:
        return None, None, rest
    if not first_month and start < today - timedelta(days=7):
        start = _safe(*_month_add(today.year, today.month, 1), first_day)  # type: ignore[arg-type]
    elif first_month and start < today - timedelta(days=180):
        start = _safe(start.year + 1, start.month, first_day)
    if start is None:
        return None, None, rest
    end_month = int(last_month) if last_month else start.month
    end = _safe(start.year, end_month, last_day)
    if end is not None and end < start:
        end = _safe(*_month_add(start.year, end_month, 1), last_day)  # type: ignore[arg-type]
    return start, end, rest


def _score(word: str, parts: list[str]) -> int:
    """2 for a surname, 1 for a first name or a patronymic, 0 for no match."""
    for rank, part in enumerate(parts):
        if len(part) < 3 or len(word) < 3:
            continue
        common = len(os.path.commonprefix([word, part]))
        need = min(len(part) - 1, 5) if rank == 0 else len(part) - 1
        if common >= max(3, need) and common >= len(word) - 3:
            return 2 if rank == 0 else 1
    return 0


def parse(
    text: str,
    today: date,
    drivers: list[dict[str, object]],
    vehicles: list[dict[str, object]],
    car_of: dict[str, str],
    driver_of: dict[str, str],
) -> dict[str, object]:
    """Guess a booking. ``car_of``: driver id → the driver's car; ``driver_of``: car id → driver."""
    problems: list[str] = []
    rest = _norm(text)

    chosen_cars: list[dict[str, object]] = []
    for car in vehicles:
        key = _plate_key(car.get("plate"))
        if key and _plate_regex(key).search(rest.translate(LATIN_TO_CYR)):
            chosen_cars.append(car)
            rest = _plate_regex(key).sub(" ", rest.translate(LATIN_TO_CYR), count=1)

    start, end, rest = _dates(rest, today)
    if start is None or end is None:
        problems.append("Не понял даты: напишите, например, «7-9» или «с 7 по 9»")

    kind = "trip"
    for name, pattern in KIND_WORDS:
        if pattern.search(rest):
            kind = name
            rest = pattern.sub(" ", rest)
            break

    words = [w for w in re.findall(r"[а-яa-z][а-яa-z\-]*", rest) if w not in STOP]
    driver_hits: dict[str, int] = {}
    car_hits: dict[str, int] = {}
    used: set[str] = set()
    for word in words:
        for person in drivers:
            parts = _norm(person.get("full_name")).split()
            if (score := _score(word, parts)):
                driver_hits[str(person["id"])] = max(driver_hits.get(str(person["id"]), 0), score)
                used.add(word)
        if not chosen_cars:
            for car in vehicles:
                names = _norm(car.get("model")).replace("-", " ").split()
                names += [alias for w in names for alias in ALIASES.get(w, ())]
                if any(len(w) >= 4 and _score(word, [w]) for w in names):
                    car_hits[str(car["id"])] = 1
                    used.add(word)
    note = " ".join(w for w in words if w not in used).strip()
    note = note[:1].upper() + note[1:] if note else ""

    candidates_drivers: list[dict[str, object]] = []
    driver_id = ""
    if driver_hits:
        best = max(driver_hits.values())
        top = [i for i, score in driver_hits.items() if score == best]
        by_id = {str(p["id"]): p for p in drivers}
        if len(top) == 1:
            driver_id = top[0]
        else:
            candidates_drivers = [{"id": i, "name": str(by_id[i]["full_name"])} for i in top]
            problems.append("Несколько водителей подходят: выберите нужного")
    elif kind != "service":
        problems.append("Не нашёл водителя среди сотрудников")

    candidates_cars: list[dict[str, object]] = []
    vehicle_id = ""
    cars = chosen_cars or [v for v in vehicles if str(v["id"]) in car_hits]
    if len(cars) == 1:
        vehicle_id = str(cars[0]["id"])
    elif len(cars) > 1:
        candidates_cars = [
            {"id": str(c["id"]), "name": f"{c['plate']} · {c['model']}"} for c in cars
        ]
        problems.append("Несколько машин подходят: выберите нужную")
    elif driver_id and driver_id in car_of:
        vehicle_id = car_of[driver_id]  # the car the driver is assigned to
    if not vehicle_id and not candidates_cars:
        problems.append("Не определил машину: назовите номер или марку")
    if not driver_id and vehicle_id and not candidates_drivers and vehicle_id in driver_of:
        driver_id = driver_of[vehicle_id]  # the driver the car is assigned to
        problems = [p for p in problems if not p.startswith("Не нашёл водителя")]

    return {
        "ok": not problems and bool(start and end),
        "values": {
            "vehicle_id": vehicle_id,
            "driver_id": driver_id,
            "date_from": start.isoformat() if start else "",
            "date_to": end.isoformat() if end else "",
            "kind": kind,
            "note": note,
        },
        "problems": problems,
        "candidates": {"drivers": candidates_drivers, "vehicles": candidates_cars},
    }
