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
DATA_DIR.mkdir(exist_ok=True, mode=0o700)
try:
    DATA_DIR.chmod(0o700)
except Exception:
    pass

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
    # Фильтр по заголовку вакансии. Пустой include = все заголовки разрешены.
    # Сравнение регистронезависимое, по вхождению подстроки.
    title_include_keywords: list = []
    title_exclude_keywords: list = []

    # LLM auto-reply settings
    llm_enabled: bool = False
    llm_auto_send: bool = False       # True = отправлять, False = только логировать черновик
    llm_use_cover_letter: bool = True  # Передавать сопроводительное письмо в контекст
    llm_use_resume: bool = True        # Включать текст резюме в системный промпт
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    # "female" (default), "male" or "neutral".
    llm_applicant_gender: str = "female"
    llm_profiles: list = None         # [{name, api_key, base_url, model, enabled}]
    llm_profile_mode: str = "fallback"  # "fallback" | "roundrobin"
    llm_openclaw_enabled: bool = False
    llm_openclaw_agent: str = "main"
    llm_openclaw_model: str = ""
    llm_openclaw_timeout: int = 120
    skip_inconsistent: bool = False  # Пропускать вакансии с несовпадением опыта
    filter_agencies: bool = False  # Исключить кадровые агентства из поиска
    filter_low_competition: bool = False  # Только вакансии с <10 откликами
    search_period_days: int = 0  # 0 = все, 1-30 = последние N дней
    llm_fill_questionnaire: bool = False  # Использовать LLM для заполнения опросников
    llm_check_interval: int = 5  # Интервал проверки чатов LLM (в минутах, мин 2)
    llm_ws_push_enabled: bool = True  # Подписаться на wss://websocket.hh.ru для мгновенных ответов
    chat_use_oauth: bool = False  # Сначала пробовать официальный OAuth-путь POST /common/chats/{id}/messages,
                                  # fallback на reverse-engineered chatik.hh.ru/api/send. Требует у аккаунта OAuth-токен.
    llm_system_prompt: str = (
        "Ты помощник соискателя работы. Отвечай вежливо и кратко (2-4 предложения) "
        "на сообщения от HR и работодателей. Пиши от первого лица. "
        "Соглашайся на предложенное время собеседования или уточни детали. "
        "Не используй слишком формальный язык."
    )

    # Шаблонные ответы на опросы (list of {keywords: [...], answer: "..."})
    questionnaire_templates: list = []
    # Ответ по умолчанию (когда ни один шаблон не подошёл)
    questionnaire_default_answer: str = "Готова рассказать подробнее на собеседовании."

    # Глобальный пул поисковых URL (выбираются на карточке каждого аккаунта)
    url_pool: list = []  # [{url, pages}, ...] или plain строки (legacy)

    # Региональный поддомен HH (например, "syktyvkar" → https://syktyvkar.hh.ru).
    # Пусто = основной домен hh.ru. OAuth и chatik всегда на основном (не региональные).
    # GitHub issue: апплай/поиск/резюме надо ходить на региональный, если задан.
    hh_region: str = ""

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

_BUILTIN_QUESTIONNAIRE_DEFAULT_ANSWER = Config.questionnaire_default_answer


def applicant_gender_forms() -> dict:
    gender = (getattr(CONFIG, "llm_applicant_gender", "") or "female").strip().lower()
    if gender in ("male", "m", "masculine", "мужской"):
        return {
            "instruction": "Пиши от первого лица, мужской род.",
            "responded": "соискатель откликнулся",
            "consistency": "будь последователен",
            "ready": "готов",
            "ready_title": "Готов",
            "default_questionnaire_answer": "Готов рассказать подробнее на собеседовании.",
        }
    if gender in ("neutral", "n", "неважно", "нейтральный"):
        return {
            "instruction": "Пиши от первого лица; избегай формулировок, где нужно выбирать мужской или женский род.",
            "responded": "отклик был отправлен",
            "consistency": "сохраняй последовательность",
            "ready": "готов(а)",
            "ready_title": "Готов(а)",
            "default_questionnaire_answer": "Готов(а) рассказать подробнее на собеседовании.",
        }
    return {
        "instruction": "Пиши от первого лица, женский род.",
        "responded": "соискатель откликнулась",
        "consistency": "будь последовательна",
        "ready": "готова",
        "ready_title": "Готова",
        "default_questionnaire_answer": "Готова рассказать подробнее на собеседовании.",
    }


def questionnaire_default_answer() -> str:
    if CONFIG.questionnaire_default_answer == _BUILTIN_QUESTIONNAIRE_DEFAULT_ANSWER:
        return applicant_gender_forms()["default_questionnaire_answer"]
    return CONFIG.questionnaire_default_answer

# Cache for _url_pages_map — invalidated in save_config() when url_pool mutates.
_url_pages_map_cache: dict | None = None
_url_pool_version: int = 0


def _url_entry(item) -> dict:
    """Нормализует элемент url_pool в {url, pages}."""
    if isinstance(item, str):
        return {"url": item.strip(), "pages": CONFIG.pages_per_url}
    return {"url": item.get("url", "").strip(), "pages": int(item.get("pages", CONFIG.pages_per_url))}


def _url_pages_map() -> dict:
    """Возвращает {url_str: pages} из CONFIG.url_pool."""
    global _url_pages_map_cache
    if _url_pages_map_cache is None:
        _url_pages_map_cache = {e["url"]: e["pages"] for u in CONFIG.url_pool for e in [_url_entry(u)]}
    return _url_pages_map_cache


_CONFIG_KEYS = [
    "pages_per_url", "max_concurrent", "response_delay", "pause_between_cycles",
    "limit_check_interval", "resume_touch_interval", "batch_responses", "min_salary",
    "auto_pause_errors", "questionnaire_default_answer", "llm_fill_questionnaire",
    "skip_inconsistent", "use_oauth_apply", "daily_apply_limit", "stop_on_hh_limit", "llm_check_interval",
    "filter_agencies", "filter_low_competition", "search_period_days",
    "hh_region", "llm_applicant_gender", "llm_auto_send", "llm_enabled",
    "llm_ws_push_enabled", "chat_use_oauth",
]


def hh_base() -> str:
    """Базовый URL HH с учётом регионального поддомена.
    Пусто → https://hh.ru. С регионом «syktyvkar» → https://syktyvkar.hh.ru.
    OAuth (`hh.ru/oauth/`) и chatik (`chatik.hh.ru`) всегда основной домен — region не применяется.
    """
    region = (getattr(CONFIG, "hh_region", "") or "").strip().lower()
    # Защита: только [a-z0-9-], чтобы не сделать SSRF через переменную.
    import re as _re
    if region and _re.match(r"^[a-z0-9][a-z0-9-]{0,40}$", region):
        return f"https://{region}.hh.ru"
    return "https://hh.ru"


def hh_url(path: str) -> str:
    """Собирает URL: hh_base() + path. path должен начинаться со слеша."""
    if not path.startswith("/"):
        path = "/" + path
    return hh_base() + path


def save_config():
    """Сохранить текущий CONFIG на диск."""
    global _url_pages_map_cache, _url_pool_version
    data = {k: getattr(CONFIG, k) for k in _CONFIG_KEYS}
    data["questionnaire_templates"] = CONFIG.questionnaire_templates
    data["letter_templates"] = CONFIG.letter_templates
    data["allowed_schedules"] = CONFIG.allowed_schedules
    data["title_include_keywords"] = CONFIG.title_include_keywords
    data["title_exclude_keywords"] = CONFIG.title_exclude_keywords
    data["auto_apply_tests"] = CONFIG.auto_apply_tests
    data["use_oauth_apply"] = CONFIG.use_oauth_apply
    data["url_pool"] = CONFIG.url_pool
    data["llm_api_key"] = CONFIG.llm_api_key
    data["llm_base_url"] = CONFIG.llm_base_url
    data["llm_model"] = CONFIG.llm_model
    data["llm_applicant_gender"] = CONFIG.llm_applicant_gender
    data["llm_enabled"] = CONFIG.llm_enabled
    data["llm_auto_send"] = CONFIG.llm_auto_send
    data["llm_use_cover_letter"] = CONFIG.llm_use_cover_letter
    data["llm_use_resume"] = CONFIG.llm_use_resume
    data["llm_system_prompt"] = CONFIG.llm_system_prompt
    data["llm_profiles"] = CONFIG.llm_profiles
    data["llm_profile_mode"] = CONFIG.llm_profile_mode
    data["llm_openclaw_enabled"] = CONFIG.llm_openclaw_enabled
    data["llm_openclaw_agent"] = CONFIG.llm_openclaw_agent
    data["llm_openclaw_model"] = CONFIG.llm_openclaw_model
    data["llm_openclaw_timeout"] = CONFIG.llm_openclaw_timeout
    _url_pool_version += 1
    _url_pages_map_cache = None
    def _write():
        with _config_write_lock:
            tmp = CONFIG_FILE.with_suffix(".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                tmp.replace(CONFIG_FILE)
                try:
                    import os as _os
                    _os.chmod(CONFIG_FILE, 0o600)  # PII (phone, telegram в letter_templates)
                except Exception:
                    pass
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
        for k in ("llm_api_key", "llm_base_url", "llm_model", "llm_system_prompt", "llm_applicant_gender"):
            if k in data and isinstance(data[k], str):
                setattr(CONFIG, k, data[k])
        for k in ("llm_enabled", "llm_auto_send", "llm_use_cover_letter", "llm_use_resume", "llm_fill_questionnaire"):
            if k in data:
                setattr(CONFIG, k, bool(data[k]))
        if "allowed_schedules" in data and isinstance(data["allowed_schedules"], list):
            CONFIG.allowed_schedules = data["allowed_schedules"]
        if "title_include_keywords" in data and isinstance(data["title_include_keywords"], list):
            CONFIG.title_include_keywords = data["title_include_keywords"]
        if "title_exclude_keywords" in data and isinstance(data["title_exclude_keywords"], list):
            CONFIG.title_exclude_keywords = data["title_exclude_keywords"]
        if "auto_apply_tests" in data:
            CONFIG.auto_apply_tests = bool(data["auto_apply_tests"])
        if "use_oauth_apply" in data:
            CONFIG.use_oauth_apply = bool(data["use_oauth_apply"])
        if "llm_profiles" in data and isinstance(data["llm_profiles"], list):
            CONFIG.llm_profiles = data["llm_profiles"]
        if "llm_profile_mode" in data and isinstance(data["llm_profile_mode"], str):
            CONFIG.llm_profile_mode = data["llm_profile_mode"]
        if "llm_openclaw_enabled" in data:
            CONFIG.llm_openclaw_enabled = bool(data["llm_openclaw_enabled"])
        if "llm_openclaw_agent" in data and isinstance(data["llm_openclaw_agent"], str):
            CONFIG.llm_openclaw_agent = data["llm_openclaw_agent"]
        if "llm_openclaw_model" in data and isinstance(data["llm_openclaw_model"], str):
            CONFIG.llm_openclaw_model = data["llm_openclaw_model"]
        if "llm_openclaw_timeout" in data:
            try:
                CONFIG.llm_openclaw_timeout = int(data["llm_openclaw_timeout"])
            except Exception:
                pass
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
                    json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
                tmp.replace(ACCOUNTS_FILE)
                try:
                    import os as _os
                    _os.chmod(ACCOUNTS_FILE, 0o600)  # cookies — owner-only
                except Exception:
                    pass
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
