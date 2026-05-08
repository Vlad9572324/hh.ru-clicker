"""JSON-backed persistence and cache helpers."""

import json
import threading
from datetime import datetime
from pathlib import Path

from .state import CONFIG, _CONFIG_KEYS, accounts_data

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

APPLIED_FILE = DATA_DIR / "applied_vacancies.json"
TEST_REQUIRED_FILE = DATA_DIR / "test_required_vacancies.json"
INTERVIEWS_FILE = DATA_DIR / "interviews.json"
ANSWER_HISTORY_FILE = DATA_DIR / "answer_history.json"
DEBUG_LOG_FILE = DATA_DIR / "debug.log"
SESSIONS_FILE = DATA_DIR / "browser_sessions.json"
CONFIG_FILE = DATA_DIR / "config.json"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"

def log_debug(message: str):
    """Записать отладочное сообщение в файл"""
    with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] {message}\n")


# ============================================================
# КЕШ В ПАМЯТИ (избегаем постоянного чтения с диска)
# ============================================================

_cache_applied: dict = None
_cache_tests: dict = None
_cache_interviews: dict = None  # Ключ: neg_id
_cache_answer_history: list = None
_cache_lock = threading.Lock()


def _load_cache():
    """Загрузить кеш из файлов (один раз при старте)"""
    global _cache_applied, _cache_tests, _cache_interviews, _cache_answer_history
    with _cache_lock:
        if _cache_applied is None:
            if APPLIED_FILE.exists():
                try:
                    with open(APPLIED_FILE, "r", encoding="utf-8") as f:
                        _cache_applied = json.load(f)
                except:
                    _cache_applied = {}
            else:
                _cache_applied = {}
        if _cache_tests is None:
            if TEST_REQUIRED_FILE.exists():
                try:
                    with open(TEST_REQUIRED_FILE, "r", encoding="utf-8") as f:
                        _cache_tests = json.load(f)
                except:
                    _cache_tests = {}
            else:
                _cache_tests = {}
        if _cache_interviews is None:
            if INTERVIEWS_FILE.exists():
                try:
                    with open(INTERVIEWS_FILE, "r", encoding="utf-8") as f:
                        _cache_interviews = json.load(f)
                except:
                    _cache_interviews = {}
            else:
                _cache_interviews = {}
        if _cache_answer_history is None:
            if ANSWER_HISTORY_FILE.exists():
                try:
                    with open(ANSWER_HISTORY_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        _cache_answer_history = data if isinstance(data, list) else []
                except:
                    _cache_answer_history = []
            else:
                _cache_answer_history = []


def _save_applied_async():
    """Сохранить applied в фоне"""
    with _cache_lock:
        data = _cache_applied.copy() if _cache_applied else {}
    with open(APPLIED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _save_tests_async():
    """Сохранить tests в фоне"""
    with _cache_lock:
        data = _cache_tests.copy() if _cache_tests else {}
    with open(TEST_REQUIRED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


_save_interviews_lock = threading.Lock()

def _save_interviews_async():
    """Сохранить interviews в фоне (атомарная запись, с защитой от параллельных записей)"""
    if not _save_interviews_lock.acquire(blocking=False):
        return  # другой поток уже сохраняет — пропускаем
    try:
        with _cache_lock:
            data = _cache_interviews.copy() if _cache_interviews else {}
        tmp = INTERVIEWS_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(INTERVIEWS_FILE)
    finally:
        _save_interviews_lock.release()


def _save_answer_history_async():
    _load_cache()
    with _cache_lock:
        data = list(_cache_answer_history or [])
    with open(ANSWER_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data[-5000:], f, ensure_ascii=False, indent=2, default=str)


def record_answer_history(kind: str, source: str, question: str, answer: str,
                          account: str = "", vacancy_id: str = "", neg_id: str = "",
                          vacancy_title: str = "", company: str = "", metadata: dict = None):
    """Persist a single answer decision for chats and questionnaires."""
    _load_cache()
    rec = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "source": source or "unknown",
        "question": question or "",
        "answer": answer or "",
        "account": account or "",
        "vacancy_id": vacancy_id or "",
        "neg_id": neg_id or "",
        "vacancy_title": vacancy_title or "",
        "company": company or "",
        "metadata": metadata or {},
    }
    with _cache_lock:
        _cache_answer_history.append(rec)
        if len(_cache_answer_history) > 5000:
            del _cache_answer_history[:-5000]
    threading.Thread(target=_save_answer_history_async, daemon=True).start()


def upsert_interview(neg_id: str, acc: str, acc_color: str = "",
                     employer: str = "", vacancy_title: str = "",
                     employer_last_msg: str = None, needs_reply: bool = None,
                     llm_reply: str = None, llm_sent: bool = None,
                     chat_not_found: bool = None, answer_source: str = None,
                     answer_metadata: dict = None, conversation: list = None):
    """Создать или обновить запись об интервью-переговоре."""
    _load_cache()
    now = datetime.now().isoformat(timespec="seconds")
    with _cache_lock:
        existing = _cache_interviews.get(neg_id, {})
        record = dict(existing)
        record["neg_id"] = neg_id
        if acc:
            record["acc"] = acc
        if acc_color:
            record["acc_color"] = acc_color
        if employer:
            record["employer"] = employer
        if vacancy_title:
            record["vacancy_title"] = vacancy_title
        if "first_seen" not in record:
            record["first_seen"] = now
        record["last_seen"] = now
        if employer_last_msg is not None:
            record["employer_last_msg"] = employer_last_msg
            record["employer_last_msg_date"] = now
        if needs_reply is not None:
            record["needs_reply"] = needs_reply
        if llm_reply is not None:
            record["llm_reply"] = llm_reply
            record["llm_reply_date"] = now
        if answer_source is not None:
            record["answer_source"] = answer_source
        if answer_metadata is not None:
            record["answer_metadata"] = answer_metadata
        if conversation is not None:
            record["conversation"] = conversation[-20:]
        if llm_sent is not None:
            # Не понижаем статус: если llm_sent=True, сохраняем его
            if not record.get("llm_sent"):
                record["llm_sent"] = llm_sent
        if chat_not_found is True:
            record["chat_not_found"] = True  # Не сбрасываем: чат закрыт навсегда
        # Определяем новое сообщение работодателя: если employer_last_msg изменилось относительно уже отвеченного,
        # разрешаем вернуть статус pending_reply, чтобы новое сообщение было обработано
        employer_msg_changed = (
            employer_last_msg is not None
            and employer_last_msg != existing.get("employer_last_msg")
            and bool(employer_last_msg)
        )
        # Выводим статус
        if record.get("chat_not_found"):
            record["status"] = "chat_closed"  # 409: permanently closed, never retried
        elif existing.get("status") == "replied" and not employer_msg_changed:
            # Сохраняем "replied" только если не пришло новое сообщение работодателя
            record["status"] = "replied"
        elif record.get("llm_reply") and not employer_msg_changed:
            record["status"] = "replied" if record.get("llm_sent") else "draft"
        elif record.get("needs_reply") is False:
            record["status"] = "no_reply_needed"
        else:
            record["status"] = "pending_reply"
        _cache_interviews[neg_id] = record
    threading.Thread(target=_save_interviews_async, daemon=True).start()


def get_no_chat_neg_ids() -> set:
    """Return set of neg_ids where chatik permanently returned 409 (chat doesn't exist)."""
    _load_cache()
    with _cache_lock:
        return {nid for nid, r in _cache_interviews.items() if r.get("chat_not_found")}


def get_interviews_list(acc: str = "", limit: int = 2000, status: str = "") -> list:
    """Вернуть список интервью, сортировка: pending_reply first, затем по дате desc."""
    _load_cache()
    with _cache_lock:
        items = list(_cache_interviews.values())
    if acc:
        items = [r for r in items if r.get("acc") == acc]
    if status:
        items = [r for r in items if r.get("status") == status]
    status_order = {"pending_reply": 0, "draft": 1, "replied": 2, "chat_closed": 3, "no_reply_needed": 4}
    # Сначала по дате desc, потом stable sort по статусу — pending всегда первые
    items.sort(key=lambda r: r.get("last_seen", "") or "", reverse=True)
    items.sort(key=lambda r: status_order.get(r.get("status", ""), 9))
    return items[:limit]


def load_browser_sessions() -> list:
    """Загрузить браузерные сессии из файла."""
    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_browser_sessions(sessions: list):
    """Сохранить браузерные сессии в файл (в фоновом потоке)."""
    def _write():
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    threading.Thread(target=_write, daemon=True).start()


def save_accounts():
    """Сохранить accounts_data на диск (в фоновом потоке)."""
    snapshot = [
        {k: v for k, v in acc.items() if not k.startswith("_")}
        for acc in accounts_data
    ]
    def _write():
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    threading.Thread(target=_write, daemon=True).start()


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



def save_config():
    """Сохранить текущий CONFIG на диск."""
    data = {k: getattr(CONFIG, k) for k in _CONFIG_KEYS}
    data["questionnaire_templates"] = CONFIG.questionnaire_templates
    data["letter_templates"] = CONFIG.letter_templates
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
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    threading.Thread(target=_write, daemon=True).start()


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
                setattr(CONFIG, k, type(old_val)(data[k]))
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
        if "llm_profiles" in data and isinstance(data["llm_profiles"], list):
            CONFIG.llm_profiles = data["llm_profiles"]
        if "llm_profile_mode" in data and isinstance(data["llm_profile_mode"], str):
            CONFIG.llm_profile_mode = data["llm_profile_mode"]
        # Миграция: если профили не заданы, но есть старый api_key, создаём один профиль
        if not CONFIG.llm_profiles and CONFIG.llm_api_key:
            CONFIG.llm_profiles = [{"name": "Основной", "api_key": CONFIG.llm_api_key,
                "base_url": CONFIG.llm_base_url, "model": CONFIG.llm_model, "enabled": True}]
    except Exception as e:
        log_debug(f"load_config error: {e}")


def add_applied(account_name: str, vacancy_id: str, info: dict = None):
    _load_cache()
    with _cache_lock:
        if account_name not in _cache_applied:
            _cache_applied[account_name] = {}
        existing = _cache_applied[account_name].get(vacancy_id, {})
        new_info = info or {}
        # Сохраняем текущие title/company, если новые значения пустые
        title = new_info.get("title") or existing.get("title", "")
        company = new_info.get("company") or existing.get("company", "")
        _cache_applied[account_name][vacancy_id] = {
            "url": f"https://hh.ru/vacancy/{vacancy_id}",
            "title": title,
            "company": company,
            "salary_from": new_info.get("salary_from") or existing.get("salary_from"),
            "salary_to": new_info.get("salary_to") or existing.get("salary_to"),
            "at": datetime.now().isoformat()
        }
    threading.Thread(target=_save_applied_async, daemon=True).start()


def add_test_vacancy(vacancy_id: str, title: str = "", company: str = "",
                     account_name: str = "", resume_hash: str = ""):
    _load_cache()
    with _cache_lock:
        if vacancy_id not in _cache_tests:
            _cache_tests[vacancy_id] = {
                "url": f"https://hh.ru/vacancy/{vacancy_id}",
                "title": title,
                "company": company,
                "account_name": account_name,
                "resume_hash": resume_hash,
                "at": datetime.now().isoformat()
            }
    threading.Thread(target=_save_tests_async, daemon=True).start()


def is_applied(account_name: str, vacancy_id: str) -> bool:
    _load_cache()
    with _cache_lock:
        return vacancy_id in _cache_applied.get(account_name, {})


def is_test(vacancy_id: str) -> bool:
    _load_cache()
    with _cache_lock:
        return vacancy_id in _cache_tests


def get_stats() -> dict:
    _load_cache()
    with _cache_lock:
        applied = _cache_applied or {}
        tests = _cache_tests or {}
    total = sum(len(v) for v in applied.values())
    by_acc = {k: len(v) for k, v in applied.items()}
    return {"total": total, "tests": len(tests), "by_acc": by_acc}


def get_applied_list(limit: int = 300) -> list:
    """Получить список последних откликов"""
    _load_cache()
    with _cache_lock:
        applied = {k: dict(v) for k, v in (_cache_applied or {}).items()}
    all_items = []
    for acc_name, vacancies in applied.items():
        for vid, info in vacancies.items():
            all_items.append({
                "account": acc_name,
                "vacancy_id": vid,
                "url": info.get("url", f"https://hh.ru/vacancy/{vid}"),
                "title": info.get("title", ""),
                "company": info.get("company", ""),
                "salary_from": info.get("salary_from"),
                "salary_to": info.get("salary_to"),
                "at": info.get("at", "")
            })
    all_items.sort(key=lambda x: x.get("at", ""), reverse=True)
    return all_items[:limit]


def get_vacancy_db(limit: int = 3000) -> list:
    """Объединённая база: applied + tests, с полем status per account."""
    _load_cache()
    with _cache_lock:
        tests = dict(_cache_tests or {})
        applied = {k: dict(v) for k, v in (_cache_applied or {}).items()}

    # vacancy_id -> {title, company, url, at, is_test, applied_by: [acc_names]}
    db: dict[str, dict] = {}

    # Сначала заполняем из applied
    for acc_name, vacancies in applied.items():
        for vid, info in vacancies.items():
            if vid not in db:
                db[vid] = {
                    "vacancy_id": vid,
                    "url": info.get("url", f"https://hh.ru/vacancy/{vid}"),
                    "title": info.get("title", ""),
                    "company": info.get("company", ""),
                    "at": info.get("at", ""),
                    "is_test": vid in tests,
                    "applied_by": [],
                }
            db[vid]["applied_by"].append(acc_name)
            # Обновляем title/company если были пустые
            if not db[vid]["title"]:
                db[vid]["title"] = info.get("title", "")
            if not db[vid]["company"]:
                db[vid]["company"] = info.get("company", "")

    # Добавляем тест-вакансии которых нет в applied
    for vid, info in tests.items():
        if vid not in db:
            db[vid] = {
                "vacancy_id": vid,
                "url": info.get("url", f"https://hh.ru/vacancy/{vid}"),
                "title": info.get("title", ""),
                "company": info.get("company", ""),
                "at": info.get("at", ""),
                "is_test": True,
                "applied_by": [],
            }
        else:
            db[vid]["is_test"] = True

    # Определяем статус
    for vid, item in db.items():
        if item["applied_by"] and item["is_test"]:
            item["status"] = "test_passed"   # 📝 тест пройден
        elif item["applied_by"]:
            item["status"] = "sent"           # ✅ откликнулись
        else:
            item["status"] = "test_pending"   # 🧪 тест не пройден

    items = sorted(db.values(), key=lambda x: x.get("at", ""), reverse=True)
    return items[:limit]


def get_test_list(limit: int = 300) -> list:
    """Получить список вакансий с тестами"""
    _load_cache()
    with _cache_lock:
        tests = dict(_cache_tests or {})
        applied = dict(_cache_applied or {})
    # Строим обратный индекс: vacancy_id -> список аккаунтов, которые откликались
    applied_by: dict[str, list[str]] = {}
    for acc_name, vacancies in applied.items():
        for vid in vacancies:
            applied_by.setdefault(vid, []).append(acc_name)
    items = []
    for vid, info in tests.items():
        items.append({
            "vacancy_id": vid,
            "url": info.get("url", f"https://hh.ru/vacancy/{vid}"),
            "title": info.get("title", ""),
            "company": info.get("company", ""),
            "account_name": info.get("account_name", ""),
            "resume_hash": info.get("resume_hash", ""),
            "applied_by": applied_by.get(vid, []),
            "at": info.get("at", "")
        })
    items.sort(key=lambda x: x.get("at", ""), reverse=True)
    return items[:limit]


__all__ = [name for name in globals() if not name.startswith("__")]
