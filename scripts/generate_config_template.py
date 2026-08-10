#!/usr/bin/env python3
"""
Генератор шаблонов конфигурации для деплоя с чистой конфигурацией.

Читает класс Config (app/config.py) и data/config.json и генерирует:

  1. `.env.template`            — переменные окружения бота с дефолтами
                                   и русскими комментариями; секреты —
                                   пустые значения/плейсхолдеры.
  2. `data/config.template.json`— полный конфиг из ДЕФОЛТОВ класса Config
                                   (не из пользовательских значений!), чтобы
                                   шаблон не содержал секретов. Описание
                                   каждого ключа — во встроенном объекте
                                   "_doc" (JSON не поддерживает комментарии).

data/config.json используется ТОЛЬКО как справочный источник: скрипт
сообщает, какие ключи пользователя не попали в шаблон и в каких ключах
присутствуют секреты/персональные данные (без вывода самих значений).
Если data/config.json отсутствует — шаблоны генерируются чисто из
дефолтов Config, без ошибки.

Режимы:
  - по умолчанию dry-run: оба шаблона печатаются в stdout с разделителями,
    ничего не записывается;
  - --apply: записать файлы. Существующий файл НЕ перезаписывается
    без --force (warn + пропуск).

Только stdlib, Python 3.10+.
Exit codes: 0 — успех, 1 — ошибка.
"""

import argparse
import copy
import json
import os
import sys
from pathlib import Path

# Все пути в коде бота относительные — работаем из корня репо.
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

ENV_TEMPLATE_PATH = Path(".env.template")
CONFIG_TEMPLATE_PATH = Path("data") / "config.template.json"
USER_CONFIG_FILE = Path("data") / "config.json"

SEP = "=" * 72


def log(msg: str) -> None:
    """Лог в stdout (конвенция проекта)."""
    print(msg)


# ============================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# ============================================================
# Найдены grep'ом по os.environ в app/ и web_app.py.
# Формат: (имя, дефолт, [строки комментария]).
# Секреты — пустые значения; публичные дефолты (например, OAuth-креды
# из APK) указаны как в коде.

ENV_SECTIONS: list[tuple[str, list[tuple[str, str, list[str]]]]] = [
    (
        "Веб-панель (web_app.py, app/routes)",
        [
            (
                "HH_BOT_HOST",
                "127.0.0.1",
                [
                    "Хост веб-панели. Нелокальные адреса (0.0.0.0 и т.п.) блокируются,",
                    "пока не задан HH_BOT_UNSAFE_EXPOSE=1 (защита от env injection).",
                ],
            ),
            ("HH_BOT_PORT", "8000", ["Порт веб-панели (uvicorn)."]),
            (
                "HH_BOT_UNSAFE_EXPOSE",
                "",
                [
                    "1/true/yes — разрешить HH_BOT_HOST вне loopback.",
                    "НЕ рекомендуется без включённого HH_BOT_API_KEY.",
                ],
            ),
            (
                "HH_BOT_API_KEY",
                "",
                [
                    "СЕКРЕТ: ключ защиты REST API и WebSocket панели",
                    "(заголовки X-API-Key / query api_key).",
                    "Пусто = авторизация выключена (опасно при доступе из сети).",
                ],
            ),
            (
                "HH_BOT_ALLOWED_ORIGINS",
                "",
                [
                    "Дополнительные хосты Origin для WS через запятую",
                    "(например, 192.168.8.206,myhost.local) — для LAN-доступа.",
                ],
            ),
        ],
    ),
    (
        "Сеть и прокси (app/hh_http.py, app/llm.py, app/manager.py)",
        [
            (
                "HH_PROXY",
                "",
                [
                    "Прокси для всех исходящих запросов к hh.ru",
                    "(обход soft-ban DDoS-Guard по IP).",
                    "Формат: socks5h://host:port или http://user:pass@host:port.",
                    "Пусто = напрямую. Имеет приоритет над hh_proxy_url из config.json.",
                ],
            ),
            (
                "LLM_PROXY",
                "",
                [
                    "Прокси для запросов к LLM API (тот же формат, что у HH_PROXY).",
                    "Пусто = напрямую.",
                ],
            ),
            (
                "HH_IMPERSONATE",
                "chrome124",
                [
                    "Версия Chrome для TLS-фингерпринта curl_cffi",
                    "(например, chrome131 для свежих проверок HH).",
                ],
            ),
        ],
    ),
    (
        "OAuth (app/oauth.py)",
        [
            (
                "HH_OAUTH_CLIENT_ID",
                "HIOMIAS39CA9DICTA7JIO64LQKQJF5AGIK74G9ITJKLNEDAOH5FHS5G1JI7FOEGD",
                [
                    "OAuth client_id приложения HH.",
                    "Дефолт извлечён из публичного APK HH Android — НЕ секрет,",
                    "переопределяется при необходимости.",
                ],
            ),
            (
                "HH_OAUTH_CLIENT_SECRET",
                "V9M870DE342BGHFRUJ5FTCGCUA1482AN0DI8C5TFI9ULMA89H10N60NOP8I4JMVS",
                [
                    "OAuth client_secret приложения HH.",
                    "Дефолт из публичного APK HH Android — НЕ секрет.",
                ],
            ),
            (
                "HH_OAUTH_CLIENT_ID_2",
                "",
                [
                    "Второй OAuth client_id (ротация/запасной). Пусто = не используется.",
                ],
            ),
            (
                "HH_OAUTH_CLIENT_SECRET_2",
                "",
                ["Второй OAuth client_secret. Пусто = не используется."],
            ),
        ],
    ),
    (
        "Чат (app/hh_chat.py)",
        [
            (
                "HH_CHATIK_BASE",
                "https://chatik.hh.ru",
                ["Базовый URL chatik-API. Менять только для отладки/проксирования."],
            ),
        ],
    ),
]


def build_env_template() -> str:
    """Собирает текст .env.template из ENV_SECTIONS."""
    lines: list[str] = [
        SEP,
        "# Шаблон переменных окружения HH.RU Auto Response Bot",
        SEP,
        "# Как использовать: скопируйте в .env / окружение systemd / блок",
        "# environment docker-compose.yml и заполните нужные значения.",
        "# Секреты оставлены пустыми — подставьте свои.",
        "# Дефолты совпадают с поведением кода (можно не задавать).",
        "",
    ]
    for section_title, entries in ENV_SECTIONS:
        lines.append(f"# --- {section_title} ---")
        lines.append("")
        for name, default, comment in entries:
            for c in comment:
                lines.append(f"# {c}")
            lines.append(f"{name}={default}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ============================================================
# ШАБЛОН КОНФИГА (дефолты класса Config)
# ============================================================
# Группы ключей по смыслу. Каждый ключ Config должен попасть ровно в одну
# группу; не попавшие автоматически уходят в группу "Разное".

CONFIG_GROUPS: list[tuple[str, list[str]]] = [
    (
        "Лимиты и задержки",
        [
            "pages_per_url",
            "max_concurrent",
            "response_delay",
            "pause_between_cycles",
            "limit_check_interval",
            "resume_touch_interval",
            "batch_responses",
            "auto_pause_errors",
            "daily_apply_limit",
            "hh_daily_limit",
            "stop_on_hh_limit",
        ],
    ),
    (
        "Фильтры вакансий",
        [
            "min_salary",
            "allowed_schedules",
            "title_include_keywords",
            "title_exclude_keywords",
            "skip_inconsistent",
            "filter_agencies",
            "filter_low_competition",
            "search_period_days",
            "min_employer_rating",
            "min_employer_reviews",
            "min_recommendations_percent",
            "skip_auto_response_vacancies",
            "prefer_quick_responses",
            "accredited_it_only",
            "related_vacancies_enabled",
        ],
    ),
    (
        "LLM",
        [
            "llm_enabled",
            "llm_auto_send",
            "llm_api_key",
            "llm_base_url",
            "llm_model",
            "llm_applicant_gender",
            "llm_profiles",
            "llm_profile_mode",
            "llm_openclaw_enabled",
            "llm_openclaw_agent",
            "llm_openclaw_model",
            "llm_openclaw_timeout",
            "llm_use_cover_letter",
            "llm_use_resume",
            "llm_use_quick_replies",
            "llm_system_prompt",
            "llm_fill_questionnaire",
            "llm_check_interval",
            "llm_ws_push_enabled",
            "hh_ai_letter_first_try",
        ],
    ),
    (
        "Отклики и клиент",
        [
            "auto_apply_tests",
            "use_oauth_apply",
            "default_client_mode",
            "chat_use_oauth",
            "hh_proxy_url",
        ],
    ),
    (
        "Регионы и шаблоны",
        [
            "hh_region",
            "url_pool",
            "letter_templates",
            "questionnaire_templates",
            "questionnaire_default_answer",
        ],
    ),
]

# Русские описания ключей для объекта "_doc" (key -> описание).
CONFIG_DOC: dict[str, str] = {
    # Лимиты и задержки
    "pages_per_url": "Сколько страниц выдачи собирать на один поисковый URL",
    "max_concurrent": "Максимальная параллельность обработки вакансий",
    "response_delay": "Задержка между откликами, секунд",
    "pause_between_cycles": "Пауза между циклами сбора, секунд",
    "limit_check_interval": "Интервал повторной проверки лимитов HH, секунд",
    "resume_touch_interval": "Интервал поднятия резюме в поиске (resume touch)",
    "batch_responses": "Размер пачки откликов в одном батче",
    "auto_pause_errors": "Авто-пауза после N ошибок подряд (0 = выключено)",
    "daily_apply_limit": "Жёсткий лимит откликов в день (0 = без ограничения)",
    "hh_daily_limit": "Дневной лимит откликов со стороны HH (обычно 200); порог "
    "для proactive limit-трекера, 0 = выключено",
    "stop_on_hh_limit": "Полная остановка при достижении лимита HH (без перепроверок)",
    # Фильтры вакансий
    "min_salary": "Минимальная зарплата в рублях (0 = без фильтра)",
    "allowed_schedules": "Фильтр по формату работы: fullDay/remote/flexible/shift/"
    "flyInFlyOut; пустой список = все форматы",
    "title_include_keywords": "Белый список ключевых слов в заголовке вакансии "
    "(регистронезависимо, по вхождению); пусто = все заголовки",
    "title_exclude_keywords": "Чёрный список ключевых слов в заголовке вакансии",
    "skip_inconsistent": "Пропускать вакансии с несовпадением опыта",
    "filter_agencies": "Исключить кадровые агентства из поиска",
    "filter_low_competition": "Только вакансии с малым числом откликов (<10)",
    "search_period_days": "Период поиска в днях: 0 = все, 1-30 = последние N дней",
    "min_employer_rating": "Минимальный рейтинг работодателя (0.0 = выкл; нужен "
    "employer_id в meta, OAuth /employers/{id}/reviews)",
    "min_employer_reviews": "Минимум отзывов работодателя для применения рейтингового фильтра",
    "min_recommendations_percent": "Минимальный процент «рекомендую работодателя» (0 = выкл)",
    "skip_auto_response_vacancies": "Пропускать вакансии auto_response (массовые авто-отклики)",
    "prefer_quick_responses": "Приоритизировать вакансии с quick_responses_allowed=true",
    "accredited_it_only": "Только аккредитованные IT-работодатели",
    "related_vacancies_enabled": "Запрашивать рекомендательный фид HH "
    "(GET /shards/vacancy/related_vacancies) раз в цикл",
    # LLM
    "llm_enabled": "Включить LLM-автоответы в чатах с HR",
    "llm_auto_send": "true = отправлять LLM-ответы автоматически; false = только логировать",
    "llm_api_key": "СЕКРЕТ: API-ключ LLM-провайдера. В шаблоне всегда пусто",
    "llm_base_url": "Базовый URL LLM API (OpenAI-совместимый)",
    "llm_model": "Модель LLM по умолчанию",
    "llm_applicant_gender": "Род текстов от лица соискателя: female / male / neutral",
    "llm_profiles": "Профили LLM-провайдеров: список {name, api_key, base_url, model, "
    "enabled}; api_key — СЕКРЕТ, в шаблоне профили пустые",
    "llm_profile_mode": "Режим переключения профилей: fallback | roundrobin",
    "llm_openclaw_enabled": "Использовать OpenClaw-агент вместо прямого LLM API",
    "llm_openclaw_agent": "Имя OpenClaw-агента",
    "llm_openclaw_model": "Модель OpenClaw (пусто = дефолт агента)",
    "llm_openclaw_timeout": "Таймаут запроса к OpenClaw, секунд",
    "llm_use_cover_letter": "Передавать сопроводительное письмо в контекст LLM",
    "llm_use_resume": "Включать текст резюме в системный промпт LLM",
    "llm_use_quick_replies": "Сначала пробовать quick_replies от HH, затем свой LLM",
    "llm_system_prompt": "Системный промпт для ответов HR (персонализируйте при деплое)",
    "llm_fill_questionnaire": "Использовать LLM для заполнения опросников",
    "llm_check_interval": "Интервал проверки чатов LLM, минут (минимум 2)",
    "llm_ws_push_enabled": "Подписка на wss://websocket.hh.ru для мгновенных ответов",
    "hh_ai_letter_first_try": "Пробовать сначала HH-Pro AI-письмо "
    "(POST /shards/hhpro_ai_letter) перед своим шаблоном",
    # Отклики и клиент
    "auto_apply_tests": "Автоматически проходить опросники при откликах",
    "use_oauth_apply": "Отклики через OAuth API (вместо web-cookies)",
    "default_client_mode": "Режим HH-клиента по умолчанию для аккаунтов без поля mode: "
    "web | mobile | auto",
    "chat_use_oauth": "Отправка в чат через OAuth POST /common/chats/{id}/messages "
    "с fallback на chatik.hh.ru",
    "hh_proxy_url": "Прокси к hh.ru (socks5h://… или http://user:pass@…); env HH_PROXY "
    "имеет приоритет над этим полем",
    # Регионы и шаблоны
    "hh_region": "Региональный поддомен HH (например, «syktyvkar»); пусто = hh.ru",
    "url_pool": "Глобальный пул поисковых URL: [{url, pages}, …] или строки (legacy)",
    "letter_templates": "Шаблоны сопроводительных писем: [{name, text}]; заполните "
    "своими данными при деплое",
    "questionnaire_templates": "Шаблоны ответов на опросники: "
    "[{keywords: [...], answer: \"...\"}]",
    "questionnaire_default_answer": "Ответ на опросник по умолчанию, "
    "когда ни один шаблон не подошёл",
}

# Ключи, в которых могут быть секреты/персональные данные пользователя.
# В шаблон их значения НЕ копируются никогда; наличие в конфиге пользователя
# только логируется (по имени ключа, без значения).
SENSITIVE_KEYS = (
    "llm_api_key",
    "llm_profiles",  # api_key внутри элементов
    "hh_proxy_url",  # может содержать user:pass
    "llm_system_prompt",
    "letter_templates",
    "questionnaire_templates",
    "questionnaire_default_answer",
)


def _config_class_defaults() -> dict:
    """Дефолты всех настроек из атрибутов класса Config (не из config.json)."""
    from app.config import Config

    defaults: dict = {}
    for name, value in vars(Config).items():
        if name.startswith("_") or callable(value):
            continue
        defaults[name] = copy.deepcopy(value)
    return defaults


def _sanitize_config_template(template: dict) -> None:
    """Гарантируем, что в шаблоне нет секретов даже после правок Config."""
    template["llm_api_key"] = ""
    profiles = template.get("llm_profiles")
    if not isinstance(profiles, list):
        template["llm_profiles"] = []
    else:
        for item in profiles:
            if isinstance(item, dict) and "api_key" in item:
                item["api_key"] = ""


def build_config_template() -> dict:
    """
    Полный конфиг из дефолтов класса Config + объект "_doc" с русскими
    описаниями ключей (группировка по смыслу — префиксом в описании).
    """
    defaults = _config_class_defaults()

    template: dict = {"_doc": {}}
    used_keys: set[str] = set()
    for group, keys in CONFIG_GROUPS:
        for key in keys:
            if key not in defaults:
                # Ключ описан в группе, но отсутствует в Config — не критично.
                log(f"⚠️ Ключ {key!r} описан в группе «{group}», но отсутствует "
                    f"в классе Config — пропущен")
                continue
            value = defaults[key]
            if key == "llm_profiles" and value is None:
                value = []  # class-level None -> пустой список профилей
            template[key] = value
            template["_doc"][key] = f"[{group}] {CONFIG_DOC.get(key, '—')}"
            used_keys.add(key)

    # Страховка: ключи Config, не попавшие ни в одну группу.
    leftover = sorted(set(defaults) - used_keys)
    for key in leftover:
        value = defaults[key]
        if key == "llm_profiles" and value is None:
            value = []
        template[key] = value
        template["_doc"][key] = f"[Разное] {CONFIG_DOC.get(key, '—')}"

    _sanitize_config_template(template)
    return template


# ============================================================
# ИНСПЕКЦИЯ data/config.json (только информационно)
# ============================================================

def inspect_user_config(template_keys: set[str]) -> None:
    """
    Читает data/config.json, если он есть. Значения НЕ используются и НЕ
    печатаются — только факты: лишие ключи и наличие секретов/персональных
    данных (по именам ключей).
    """
    if not USER_CONFIG_FILE.exists():
        log(f"ℹ️ {USER_CONFIG_FILE} отсутствует — шаблоны генерируются "
            f"чисто из дефолтов класса Config")
        return

    try:
        with open(USER_CONFIG_FILE, "r", encoding="utf-8") as f:
            user_data = json.load(f)
        if not isinstance(user_data, dict):
            log(f"⚠️ {USER_CONFIG_FILE}: ожидался JSON-объект, шаблоны "
                f"генерируются из дефолтов Config")
            return
    except Exception as e:
        log(f"⚠️ Не удалось прочитать {USER_CONFIG_FILE} ({e}) — шаблоны "
            f"генерируются из дефолтов Config")
        return

    log(f"ℹ️ {USER_CONFIG_FILE} найден ({len(user_data)} ключей) — значения "
        f"НЕ копируются в шаблон (защита от утечки секретов)")

    extra = sorted(set(user_data) - template_keys - {"_doc"})
    if extra:
        log(f"⚠️ Ключи пользователя вне шаблона (не войдут в config.template.json): "
            f"{', '.join(extra)}")

    found_sensitive: list[str] = []
    for key in SENSITIVE_KEYS:
        if key not in user_data:
            continue
        value = user_data[key]
        if key == "llm_profiles" and isinstance(value, list):
            if any(isinstance(p, dict) and p.get("api_key") for p in value):
                found_sensitive.append(f"{key} (api_key в профилях)")
        elif key in ("letter_templates", "questionnaire_templates") and isinstance(value, list):
            if value:
                found_sensitive.append(key)
        elif isinstance(value, str) and value.strip():
            found_sensitive.append(key)
    if found_sensitive:
        log(f"⚠️ В конфиге пользователя есть секреты/персональные данные: "
            f"{', '.join(found_sensitive)} — в шаблоны они НЕ попадают")


# ============================================================
# ЗАПИСЬ ФАЙЛОВ
# ============================================================

def write_target(path: Path, content: str, apply: bool, force: bool) -> bool:
    """Dry-run: печатает содержимое с разделителем. --apply: пишет файл.
    Возвращает True, если файл был записан."""
    if not apply:
        log("")
        log(SEP)
        log(f"DRY-RUN — содержимое {path} (ничего не записывается):")
        log(SEP)
        print(content)
        log(SEP)
        log(f"КОНЕЦ DRY-RUN {path}")
        log(SEP)
        return False

    if path.exists() and not force:
        log(f"⚠️ {path} уже существует — пропущен (используйте --force "
            f"для перезаписи)")
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    log(f"✅ Записан {path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Генератор шаблонов конфигурации для чистого деплоя: "
        ".env.template и data/config.template.json из дефолтов класса Config "
        "(без пользовательских секретов из data/config.json).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="записать файлы (по умолчанию — dry-run: печать в stdout)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="перезаписать существующие файлы-шаблоны (по умолчанию — пропуск)",
    )
    args = parser.parse_args()

    try:
        env_template = build_env_template()
        config_template = build_config_template()

        template_keys = set(config_template) - {"_doc"}
        log("Генерация шаблонов конфигурации (дефолты класса Config, "
            "без секретов пользователя)")
        inspect_user_config(template_keys)

        wrote = 0
        if write_target(ENV_TEMPLATE_PATH, env_template, args.apply, args.force):
            wrote += 1
        config_content = json.dumps(config_template, ensure_ascii=False, indent=2) + "\n"
        if write_target(CONFIG_TEMPLATE_PATH, config_content, args.apply, args.force):
            wrote += 1

        if args.apply:
            if wrote:
                log(f"Готово: записано файлов: {wrote}")
            else:
                log("Готово: ничего не записано (целевые файлы уже существуют, "
                    "используйте --force для перезаписи)")
        else:
            log("")
            log("Dry-run завершён. Добавьте --apply, чтобы записать файлы.")
        return 0
    except Exception as e:
        log(f"❌ Ошибка генерации шаблонов: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
