"""Shared runtime configuration and account state."""


# Аккаунты загружаются из data/accounts.json при старте.
accounts_data: list = []


class Config:
    """Глобальные настройки (можно менять в runtime)"""
    pages_per_url = 40
    max_concurrent = 20
    response_delay = 1
    pause_between_cycles = 60
    limit_check_interval = 30
    resume_touch_interval = 4
    batch_responses = 3
    min_salary = 0  # Минимальная зарплата в руб (0 = без фильтра)
    auto_pause_errors = 5  # Авто-пауза после N ошибок подряд (0 = выключено)

    # Настройки LLM-автоответов
    llm_enabled: bool = False
    llm_auto_send: bool = True        # True означает отправку, False - только логирование черновика
    llm_use_cover_letter: bool = True  # Передавать сопроводительное письмо в контекст
    llm_use_resume: bool = True        # Включать текст резюме в системный промпт
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_profiles: list = None         # [{name, api_key, base_url, model, enabled}]
    llm_profile_mode: str = "fallback"  # "fallback" | "roundrobin"
    llm_fill_questionnaire: bool = False  # Использовать LLM для заполнения опросников
    llm_system_prompt: str = (
        "Ты помощник соискателя работы. Отвечай вежливо и кратко (2-4 предложения) "
        "на сообщения от HR и работодателей. Пиши от первого лица, женский род. "
        "Соглашайся на предложенное время собеседования или уточни детали. "
        "Не используй слишком формальный язык."
    )

    # Шаблонные ответы на опросы (list of {keywords: [...], answer: "..."})
    questionnaire_templates: list = []
    # Ответ по умолчанию (когда ни один шаблон не подошёл)
    questionnaire_default_answer: str = "Готова рассказать подробнее на собеседовании."

    # Глобальный пул поисковых URL (выбираются на карточке каждого аккаунта)
    url_pool: list = []  # [{url, pages}, ...] или plain строки (legacy)

    # Шаблоны сопроводительных писем (list of {name: str, text: str})
    letter_templates: list = [
        {
            "name": "Стандартное",
            "text": (
                "Здравствуйте!\n\n"
                "Я выражаю искренний интерес к возможности присоединиться к вашей компании.\n\n"
                "Я ознакомился с деятельностью вашей организации и уверен, что мой опыт и навыки "
                "смогут внести вклад в вашу команду.\n\n"
                "Хочу отметить, что я всегда готов обучаться новому и развиваться в профессиональном плане.\n\n"
                "Считаю, что ваша компания предоставляет отличные возможности для роста и "
                "самосовершенствования, и мне бы хотелось стать частью вашей команды.\n\n"
                "С уважением,\n[ИМЯ]\n[t.me: @username]\n[📞 телефон]"
            ),
        }
    ]



CONFIG = Config()
CONFIG.llm_profiles = []

_CONFIG_KEYS = [
    "pages_per_url", "max_concurrent", "response_delay", "pause_between_cycles",
    "limit_check_interval", "resume_touch_interval", "batch_responses", "min_salary",
    "auto_pause_errors", "questionnaire_default_answer", "llm_fill_questionnaire",
]


def url_entry(item) -> dict:
    """Normalize an url_pool item into {url, pages}."""
    if isinstance(item, str):
        return {"url": item.strip(), "pages": CONFIG.pages_per_url}
    return {"url": item.get("url", "").strip(), "pages": int(item.get("pages", CONFIG.pages_per_url))}


def url_pages_map() -> dict:
    """Return {url_str: pages} from CONFIG.url_pool."""
    return {e["url"]: e["pages"] for u in CONFIG.url_pool for e in [url_entry(u)]}


# Приватные имена для обратной совместимости с текущим кодом routes и bot.
_url_entry = url_entry
_url_pages_map = url_pages_map
