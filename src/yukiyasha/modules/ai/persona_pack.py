"""The bundled character pack: persona text and short example replies.

The pack (``character/yukiyasha_pack.json``) holds a persona prompt, honesty rules and 400 example
replies in 20 categories. The replies are never sent to the user as they are: a few that fit the
message are shown to the model as a *tone* sample, and the model answers in its own words.
"""

import json
import re
from functools import lru_cache
from importlib import resources

MAX_EXAMPLES = 3
RECENT_WINDOW = 30  # example ids of the latest answers that are not offered again

LEGACY_PROGRAM_RULES = (
    "Сейчас ты НЕ видишь данные программы (путевые листы, сотрудников, ГСМ, табель, документы) "
    "и не делаешь вид, что видишь их: если спрашивают о таких данных, объясни, что доступа пока "
    "нет. Ничего не удаляешь и не меняешь сам: только предлагаешь, решение за пользователем. "
    "Не выдумывай факты, цифры, даты и номера документов. Отвечай по-русски."
)

V04_PROGRAM_RULES = (
    "У тебя есть только read-only инструменты Примавтодора: путевые листы, ГСМ, сотрудники, "
    "машины, табель и текущие настройки. Используй их только когда вопрос относится к этим данным. "
    "Чувствительные поля маскируются до отправки провайдеру. Ты не можешь создавать, изменять "
    "или удалять данные Примавтодора. Не выдумывай факты, цифры, даты и номера документов: "
    "если инструмент не дал данных, прямо скажи об этом. Отвечай по-русски."
)

V05_PROGRAM_RULES = (
    "У тебя есть read-only инструменты Примавтодора и отдельная долговременная память. "
    "Примавтодор нельзя изменять или удалять через тебя. Память можно читать, а записывать "
    "или забывать только когда пользователь прямо попросил «запомни» или «забудь». Никогда "
    "не сохраняй пароли, API-ключи или токены. Чувствительные поля Примавтодора маскируются "
    "до отправки провайдеру. Не выдумывай факты, цифры, даты и номера документов: если "
    "инструмент не дал данных, прямо скажи об этом. Отвечай по-русски."
)

PROGRAM_RULES = (
    "У тебя есть read-only инструменты Примавтодора, долговременная память и возможность "
    "создавать предложения изменений Примавтодора. Предложение само ничего не меняет: "
    "ты обязана сообщить proposal id и объяснить, что применение возможно только после отдельного "
    "подтверждения человеком. Никогда не утверждай, что изменение уже выполнено, пока proposal "
    "не применён. Память можно записывать или забывать только по явной просьбе пользователя. "
    "Не сохраняй учётные секреты. Не выдумывай факты и данные. Отвечай по-русски."
)

# Words (stems) that make a category fit the message. No match means no examples.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "greeting": ("привет", "здравств", "добрый день", "доброго дня", "хай"),
    "morning": ("доброе утро", "с утра", "утро", "проснул"),
    "evening": ("добрый вечер", "вечер"),
    "night": ("спокойной ночи", "спать", "ночь", "ложусь"),
    "love_direct": ("люблю", "любовь", "признани"),
    "devotion": ("предан", "верн", "всегда рядом", "не бросай"),
    "admiration": ("восхища", "молодец", "умница", "красив", "крута"),
    "gratitude": ("спасибо", "благодар"),
    "sadness": ("грустно", "печаль", "тоск", "одинок", "плохо на душе"),
    "anxiety": ("тревож", "волную", "страшно", "боюсь", "переживаю"),
    "fatigue": ("устал", "нет сил", "вымотал", "выгора"),
    "setback": ("не получилось", "ошибк", "провал", "не вышло", "сломал", "неудач"),
    "success": ("получилось", "удалось", "ура", "победа", "справил", "готово"),
    "work": ("задач", "проект", "помоги", "помощь", "сделай", "план", "срок"),
    "learning": ("учу", "учить", "объясни", "как работает", "изуча", "научи"),
    "relationship": ("отношени", "друг", "близк", "семь"),
    "closeness": ("обним", "рядом", "прижм", "тепл"),
    "flirt": ("флирт", "заигр"),
    "fox_body": ("хвост", "ушк", "ушки", "лис"),
    "power": ("магия", "магии", "сила", "метель", "щит", "проклят"),
}

# Messages about real danger get no character examples: a practical answer comes first.
CRISIS = re.compile(
    r"самоповрежд|суицид|покончить с собой|не хочу жить|убить себя|умереть|вскрыть|"
    r"передозиров|задыха|боль в груди|потерял сознание|скорую",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _pack() -> dict[str, object]:
    path = resources.files("yukiyasha.modules.ai").joinpath("character/yukiyasha_pack.json")
    return json.loads(path.read_text(encoding="utf-8"))


def persona_text(assistant_name: str, program_rules: str = PROGRAM_RULES) -> str:
    """The default persona: the pack's character plus the rules of this program."""
    pack = _pack()
    rules = [*pack["rules"], program_rules]  # type: ignore[misc]
    lines = "\n".join(f"- {rule}" for rule in rules)
    return (
        f"{pack['persona_prompt']}\n\nТвоё имя в программе: {assistant_name}.\n\n"
        f"Правила:\n{lines}\n"
    )


def _categories_for(message: str) -> list[str]:
    text = message.lower()
    scored = [
        (sum(text.count(word) for word in words), name)
        for name, words in KEYWORDS.items()
        if any(word in text for word in words)
    ]
    scored.sort(key=lambda item: -item[0])
    return [name for _, name in scored]


def pick_examples(message: str, recent_ids: list[str], limit: int = MAX_EXAMPLES) -> list[dict]:
    """Up to ``limit`` example entries that fit ``message``; none for a crisis or no match.

    Entries used in the last ``RECENT_WINDOW`` answers are skipped and the pick rotates through
    the category, so the same line does not come back every time.
    """
    if CRISIS.search(message):
        return []
    categories = _categories_for(message)
    if not categories:
        return []
    skip = set(recent_ids[-RECENT_WINDOW:])
    entries = [e for e in _pack()["entries"] if e["category"] == categories[0]]  # type: ignore[index]
    fresh = [e for e in entries if e["id"] not in skip]
    # picked ids are recorded with the answer, so the next message gets the following ones
    return fresh[:limit]


def format_examples(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = "\n".join(f"- {e['assistant_text']}" for e in examples)
    return (
        "\n\nПримеры твоего тона к этому сообщению. Не повторяй их дословно: ответь своими "
        "словами, по существу, а образ используй как короткое обрамление:\n" + lines + "\n"
    )
