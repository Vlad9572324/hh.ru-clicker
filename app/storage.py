"""
Data storage: applied vacancies, tests, interviews, browser sessions.
In-memory cache with async disk persistence.
"""

import json
import copy
import threading
from datetime import datetime
from pathlib import Path

from app.logging_utils import log_debug

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

APPLIED_FILE = DATA_DIR / "applied_vacancies.json"
TESTS_FILE = DATA_DIR / "test_required_vacancies.json"
INTERVIEWS_FILE = DATA_DIR / "interviews.json"
SESSIONS_FILE = DATA_DIR / "browser_sessions.json"


# ============================================================
# КЕШ В ПАМЯТИ (избегаем постоянного чтения с диска)
# ============================================================

_cache_applied: dict = None
_cache_tests: dict = None
_cache_interviews: dict = None  # keyed by neg_id
_cache_lock = threading.Lock()


def _load_cache():
    """Загрузить кеш из файлов (один раз при старте)"""
    global _cache_applied, _cache_tests, _cache_interviews
    with _cache_lock:
        if _cache_applied is None:
            if APPLIED_FILE.exists():
                try:
                    with open(APPLIED_FILE, "r", encoding="utf-8") as f:
                        _cache_applied = json.load(f)
                except (json.JSONDecodeError, OSError, ValueError) as e:
                    log_debug(f"⚠️ Ошибка загрузки {APPLIED_FILE}: {e}")
                    _cache_applied = {}
            else:
                _cache_applied = {}
        if _cache_tests is None:
            if TESTS_FILE.exists():
                try:
                    with open(TESTS_FILE, "r", encoding="utf-8") as f:
                        _cache_tests = json.load(f)
                except (json.JSONDecodeError, OSError, ValueError) as e:
                    log_debug(f"⚠️ Ошибка загрузки {TESTS_FILE}: {e}")
                    _cache_tests = {}
            else:
                _cache_tests = {}
        if _cache_interviews is None:
            if INTERVIEWS_FILE.exists():
                try:
                    with open(INTERVIEWS_FILE, "r", encoding="utf-8") as f:
                        _cache_interviews = json.load(f)
                except (json.JSONDecodeError, OSError, ValueError) as e:
                    log_debug(f"⚠️ Ошибка загрузки {INTERVIEWS_FILE}: {e}")
                    _cache_interviews = {}
            else:
                _cache_interviews = {}


_save_applied_lock = threading.Lock()

def _save_applied_async():
    """Сохранить applied в фоне (atomic write)"""
    lock = _save_applied_lock  # local ref на случай reload модуля
    if not lock.acquire(blocking=False):
        return  # another save in progress
    try:
        with _cache_lock:
            data = copy.deepcopy(_cache_applied) if _cache_applied else {}
        tmp = APPLIED_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(APPLIED_FILE)
    except Exception as e:
        log_debug(f"_save_applied_async error: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
    finally:
        lock.release()


_save_tests_lock = threading.Lock()

def _save_tests_async():
    """Сохранить tests в фоне (atomic write)"""
    lock = _save_tests_lock
    if not lock.acquire(blocking=False):
        return
    try:
        with _cache_lock:
            data = copy.deepcopy(_cache_tests) if _cache_tests else {}
        tmp = TESTS_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(TESTS_FILE)
    except Exception as e:
        log_debug(f"_save_tests_async error: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
    finally:
        lock.release()


_save_interviews_lock = threading.Lock()

def _save_interviews_async():
    """Сохранить interviews в фоне (атомарная запись, с защитой от параллельных записей)"""
    lock = _save_interviews_lock
    if not lock.acquire(blocking=False):
        return  # другой поток уже сохраняет — пропускаем
    try:
        with _cache_lock:
            data = copy.deepcopy(_cache_interviews) if _cache_interviews else {}
        tmp = INTERVIEWS_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(INTERVIEWS_FILE)
    finally:
        lock.release()


def upsert_interview(neg_id: str, acc: str, acc_color: str = "",
                     employer: str = "", vacancy_title: str = "",
                     employer_last_msg: str = None, needs_reply: bool = None,
                     llm_reply: str = None, llm_sent: bool = None,
                     chat_not_found: bool = None, chat_status: str = None,
                     replied_msg_id: str = None):
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
        if llm_sent is not None:
            # Never downgrade: once llm_sent=True, keep it
            if not record.get("llm_sent"):
                record["llm_sent"] = llm_sent
        # Persisted dedup key: last msg_id we successfully replied to.
        # Used by LLM loop to skip after restart (in-memory dedup is lost).
        if replied_msg_id:
            record["replied_msg_id"] = str(replied_msg_id)
        if chat_not_found is True:
            record["chat_not_found"] = True  # never reset — chat is permanently closed
        if chat_status is not None:
            record["chat_status"] = chat_status
        # Detect new employer message: if employer_last_msg changed vs what was already replied,
        # allow status to go back to pending_reply so the new message gets handled
        employer_msg_changed = (
            employer_last_msg is not None
            and employer_last_msg != existing.get("employer_last_msg")
            and bool(employer_last_msg)
        )
        # Derive status
        if record.get("chat_not_found"):
            record["status"] = "chat_closed"  # 409: permanently closed, never retried
        elif existing.get("status") == "replied" and not employer_msg_changed:
            # Keep "replied" only if no new employer message arrived
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


def get_replied_keys() -> set:
    """Persisted LLM dedup: returns {(neg_id, replied_msg_id)} for chats already replied to.
    Used to seed `state.llm_replied_msgs` on startup so we don't re-reply after restart.
    """
    _load_cache()
    with _cache_lock:
        return {
            (str(nid), str(r["replied_msg_id"]))
            for nid, r in _cache_interviews.items()
            if r.get("llm_sent") and r.get("replied_msg_id")
        }


def get_interviews_list(acc: str = "", limit: int = 2000, status: str = "") -> list:
    """Вернуть список интервью, сортировка: pending_reply first, затем по дате desc."""
    _load_cache()
    with _cache_lock:
        items = list(_cache_interviews.values())
    if acc:
        items = [r for r in items if r.get("acc") == acc]
    if status:
        items = [r for r in items if r.get("status") == status or r.get("chat_status") == status]
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


_save_sessions_lock = threading.Lock()


def save_browser_sessions(sessions: list):
    """Сохранить браузерные сессии в файл (в фоновом потоке)."""
    snapshot = copy.deepcopy(sessions)
    def _write():
        with _save_sessions_lock:
            tmp = SESSIONS_FILE.with_suffix(".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False, indent=2)
                tmp.replace(SESSIONS_FILE)
            except Exception as e:
                log_debug(f"save_browser_sessions error: {e}")
                tmp.unlink(missing_ok=True)
    threading.Thread(target=_write, daemon=True).start()


def add_applied(account_name: str, vacancy_id: str, info: dict = None):
    _load_cache()
    with _cache_lock:
        if account_name not in _cache_applied:
            _cache_applied[account_name] = {}
        existing = _cache_applied[account_name].get(vacancy_id, {})
        new_info = info or {}
        # Preserve existing title/company if new info has empty values
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
    # Build reverse lookup: vacancy_id -> list of account_names that applied
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
