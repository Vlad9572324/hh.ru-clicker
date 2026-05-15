"""
Configuration: Config class, accounts_data, save/load functions, URL helpers.
"""

import json
import threading
from pathlib import Path

from app.logging_utils import log_debug
# Используем storage executor вместо своего fire-and-forget thread per save.
try:
    from app.storage import _schedule_save
except Exception:
    _schedule_save = None  # cycle-safe fallback

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

CONFIG_FILE = DATA_DIR / "config.json"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"

# Защищаем write+rename последовательность от конкурентных вызовов из разных потоков.
_config_write_lock = threading.Lock()
_accounts_write_lock = threading.Lock()


# ============================================================
# АККАУНТЫ
# ============================================================

# Загружается из data/accounts.json при старте (через load_accounts())
accounts_data: list = []


# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

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
    auto_apply_tests: bool = False  # Автоматически проходить опросники при откликах
    use_oauth_apply: bool = False  # Использовать OAuth API для откликов (вместо web cookies)
    daily_apply_limit: int = 0  # Жёсткий лимит откликов в день (0 = без ограничения)
    stop_on_hh_limit: bool = True  # Полная остановка при HH лимите (не перепроверять)
    # Фильтр по формату работы (пустой = без фильтра, все форматы)
    # Возможные значения: "fullDay", "remote", "flexible", "shift", "flyInFlyOut"
    allowed_schedules: list = []

    # LLM auto-reply settings
    llm_enabled: bool = False
    llm_auto_send: bool = False       # True = отправлять, False = только логировать черновик
    llm_use_cover_letter: bool = True  # Передавать сопроводительное письмо в контекст
    llm_use_resume: bool = True        # Включать текст резюме в системный промпт
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_profiles: list = None         # [{name, api_key, base_url, model, enabled}]
    llm_profile_mode: str = "fallback"  # "fallback" | "roundrobin"
    skip_inconsistent: bool = False  # Пропускать вакансии с несовпадением опыта
    filter_agencies: bool = False  # Исключить кадровые агентства из поиска
    filter_low_competition: bool = False  # Только вакансии с <10 откликами
    search_period_days: int = 0  # 0 = все, 1-30 = последние N дней
    llm_fill_questionnaire: bool = False  # Использовать LLM для заполнения опросников
    llm_check_interval: int = 5  # Интервал проверки чатов LLM (в минутах, мин 2)
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


def _url_entry(item) -> dict:
    """Нормализует элемент url_pool в {url, pages}."""
    if isinstance(item, str):
        return {"url": item.strip(), "pages": CONFIG.pages_per_url}
    return {"url": item.get("url", "").strip(), "pages": int(item.get("pages", CONFIG.pages_per_url))}


def _url_pages_map() -> dict:
    """Возвращает {url_str: pages} из CONFIG.url_pool."""
    return {e["url"]: e["pages"] for u in CONFIG.url_pool for e in [_url_entry(u)]}


_CONFIG_KEYS = [
    "pages_per_url", "max_concurrent", "response_delay", "pause_between_cycles",
    "limit_check_interval", "resume_touch_interval", "batch_responses", "min_salary",
    "auto_pause_errors", "questionnaire_default_answer", "llm_fill_questionnaire",
    "skip_inconsistent", "use_oauth_apply", "daily_apply_limit", "stop_on_hh_limit", "llm_check_interval",
    "filter_agencies", "filter_low_competition", "search_period_days",
]


def save_config():
    """Сохранить текущий CONFIG на диск."""
    data = {k: getattr(CONFIG, k) for k in _CONFIG_KEYS}
    data["questionnaire_templates"] = CONFIG.questionnaire_templates
    data["letter_templates"] = CONFIG.letter_templates
    data["allowed_schedules"] = CONFIG.allowed_schedules
    data["auto_apply_tests"] = CONFIG.auto_apply_tests
    data["use_oauth_apply"] = CONFIG.use_oauth_apply
    data["url_pool"] = CONFIG.url_pool
    data["llm_api_key"] = CONFIG.llm_api_key
    data["llm_base_url"] = CONFIG.llm_base_url
    data["llm_model"] = CONFIG.llm_model
    data["llm_enabled"] = CONFIG.llm_enabled
    data["llm_auto_send"] = CONFIG.llm_auto_send
    data["llm_use_cover_letter"] = CONFIG.llm_use_cover_letter
    data["llm_use_resume"] = CONFIG.llm_use_resume
    data["llm_system_prompt"] = CONFIG.llm_system_prompt
    data["llm_profiles"] = CONFIG.llm_profiles
    data["llm_profile_mode"] = CONFIG.llm_profile_mode
    def _write():
        with _config_write_lock:
            tmp = CONFIG_FILE.with_suffix(".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                tmp.replace(CONFIG_FILE)
            except Exception as e:
                log_debug(f"save_config error: {e}")
                tmp.unlink(missing_ok=True)
    (_schedule_save(_write) if _schedule_save else threading.Thread(target=_write, daemon=True).start())


def load_config():
    """Загрузить CONFIG с диска (если файл есть)."""
    if not CONFIG_FILE.exists():
        return
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in _CONFIG_KEYS:
            if k in data:
                old_val = getattr(CONFIG, k)
                try:
                    setattr(CONFIG, k, type(old_val)(data[k]))
                except (ValueError, TypeError):
                    log_debug(f"⚠️ Невалидное значение конфига {k}={data[k]!r}, пропуск")
        if "questionnaire_templates" in data and isinstance(data["questionnaire_templates"], list):
            CONFIG.questionnaire_templates = data["questionnaire_templates"]
        if "letter_templates" in data and isinstance(data["letter_templates"], list):
            CONFIG.letter_templates = data["letter_templates"]
        if "url_pool" in data and isinstance(data["url_pool"], list):
            CONFIG.url_pool = data["url_pool"]
        for k in ("llm_api_key", "llm_base_url", "llm_model", "llm_system_prompt"):
            if k in data and isinstance(data[k], str):
                setattr(CONFIG, k, data[k])
        for k in ("llm_enabled", "llm_auto_send", "llm_use_cover_letter", "llm_use_resume", "llm_fill_questionnaire"):
            if k in data:
                setattr(CONFIG, k, bool(data[k]))
        if "allowed_schedules" in data and isinstance(data["allowed_schedules"], list):
            CONFIG.allowed_schedules = data["allowed_schedules"]
        if "auto_apply_tests" in data:
            CONFIG.auto_apply_tests = bool(data["auto_apply_tests"])
        if "use_oauth_apply" in data:
            CONFIG.use_oauth_apply = bool(data["use_oauth_apply"])
        if "llm_profiles" in data and isinstance(data["llm_profiles"], list):
            CONFIG.llm_profiles = data["llm_profiles"]
        if "llm_profile_mode" in data and isinstance(data["llm_profile_mode"], str):
            CONFIG.llm_profile_mode = data["llm_profile_mode"]
        # Migration: if no profiles defined but old-style api_key exists, create one profile
        if not CONFIG.llm_profiles and CONFIG.llm_api_key:
            CONFIG.llm_profiles = [{"name": "Основной", "api_key": CONFIG.llm_api_key,
                "base_url": CONFIG.llm_base_url, "model": CONFIG.llm_model, "enabled": True}]
    except Exception as e:
        log_debug(f"load_config error: {e}")


def save_accounts():
    """Сохранить accounts_data на диск (в фоновом потоке)."""
    snapshot = [
        {k: v for k, v in acc.items() if not k.startswith("_")}
        for acc in accounts_data
    ]
    def _write():
        with _accounts_write_lock:
            tmp = ACCOUNTS_FILE.with_suffix(".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False, indent=2)
                tmp.replace(ACCOUNTS_FILE)
            except Exception as e:
                log_debug(f"save_accounts error: {e}")
                tmp.unlink(missing_ok=True)
    (_schedule_save(_write) if _schedule_save else threading.Thread(target=_write, daemon=True).start())


def load_accounts():
    """Загрузить accounts_data с диска (если файл есть)."""
    if not ACCOUNTS_FILE.exists():
        save_accounts()  # первый запуск — сохраняем текущие дефолты
        return
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            accounts_data.clear()
            accounts_data.extend(data)
    except Exception as e:
        log_debug(f"load_accounts error: {e}")
