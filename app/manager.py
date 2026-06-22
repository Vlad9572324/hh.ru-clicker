"""
BotManager — core bot logic with per-account worker threads.
"""

import asyncio
import aiohttp
import json
import random
from datetime import datetime, timedelta
from collections import deque
from pathlib import Path
import time
import threading
import requests
try:
    from zoneinfo import ZoneInfo
    _MSK = ZoneInfo("Europe/Moscow")
except Exception:
    _MSK = None  # fallback на local

from app.logging_utils import log_debug, log_exception, _is_login_page


def _today_msk() -> str:
    """Дата по Москве. HH работает в MSK; используем её как «день» бота
    чтобы midnight rollover не зависел от TZ контейнера (Docker = UTC по дефолту).
    """
    if _MSK is not None:
        return datetime.now(_MSK).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def _fingerprint_key(key: str) -> str:
    """Безопасный fingerprint API-ключа для UI: first4…last4 (N симв.).
    Полный ключ никогда не уходит в snapshot, но юзер видит что именно
    сохранилось (особенно полезно после релоада когда type=password input
    показывает только звёздочки)."""
    if not key:
        return ""
    s = (key or "").strip()
    if len(s) <= 12:
        return f"••• ({len(s)} симв.)"
    return f"{s[:4]}…{s[-4:]} ({len(s)} симв.)"

from app.config import (
    CONFIG, accounts_data,
    save_config, load_config, save_accounts, load_accounts,
    _url_entry, _url_pages_map, hh_base, questionnaire_default_answer,
)

from app.storage import (
    _load_cache, _cache_applied, _cache_lock,
    add_applied, is_applied, add_test_vacancy, is_test, get_stats,
    load_browser_sessions, save_browser_sessions,
    upsert_interview, get_no_chat_neg_ids, get_replied_keys,
    _schedule_save,
)

from app.oauth import (
    _oauth_apply,
    get_oauth_status,
)

from app.hh_api import (
    get_headers, parse_ids, parse_vacancy_meta, parse_salaries,
    parse_work_schedules, extract_search_query,
)

from app.llm import generate_llm_reply

from app.hh_apply import (
    send_response_async, fill_and_submit_questionnaire,
    _check_vacancy_before_apply, check_limit, touch_resume,
)

from app.hh_chat import (
    _fetch_chat_list, _build_thread_from_chat_item, _check_chat_locked,
    _fetch_chat_history,
    send_negotiation_message,
)

from app.hh_resume import (
    fetch_resume_text, fetch_resume_stats, fetch_resume_view_history,
    _resume_cache, _RESUME_CACHE_TTL,
)

from app.hh_negotiations import (
    fetch_hh_negotiations_stats, fetch_hh_possible_offers,
)

from app.state import AccountState

LLM_LOG_FILE = Path("data") / "llm_log.jsonl"

# -- Async page fetcher (used only by BotManager) --

async def fetch_page(session, url, sem):
    async with sem:
        try:
            await asyncio.sleep(0.05)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                html = await r.text()
                # Логируем только не-200 и аномальные размеры — иначе hundreds
                # of disk writes per cycle давят RotatingFileHandler (swarm-16 #9).
                if r.status != 200 or len(html) < 1000:
                    log_debug(f"⚠️ URL: {url} | Статус: {r.status} | Размер: {len(html)}")
                return html
        except Exception as e:
            log_debug(f"❌ ОШИБКА при загрузке: {url} | {type(e).__name__}: {e}")
            return ""


# ============================================================
# BOT MANAGER
# ============================================================

class BotManager:
    def __init__(self):
        self.paused = False
        self._stop_event = threading.Event()
        self.account_states: list[AccountState] = []
        self.activity_log: deque = deque(maxlen=100)
        self.recent_responses: deque = deque(maxlen=100)
        self.llm_log: deque = deque(maxlen=200)    # LLM reply history
        # Защищает list(deque) snapshot от race с concurrent appendleft.
        # В CPython deque.appendleft атомарен, но `list(deque)` иногда падает с RuntimeError при гонке.
        self._deque_lock = threading.Lock()
        self.vacancy_queues: dict = {}
        self._start_time: datetime = None
        self.temp_sessions: list = load_browser_sessions()  # сессии из браузера (персистентные)
        self.temp_states: dict[int, AccountState] = {}  # temp_idx → AccountState для активных сессий
        # Global dedup across all accounts: {(cur_pid, neg_id, last_msg_id)}
        # Prevents double-sends when multiple accounts share the same HH user (same cur_pid)
        self._llm_sent_global: set = set()
        self._llm_sent_by_neg_id: dict = {}  # индекс neg_id -> set(global_key) для O(1) очистки
        self._llm_sent_lock = threading.Lock()
        # HR contacts collected from contactInfo during pre-checks
        self.hr_contacts: list = []  # capped at 500
        self._hr_contacts_lock = threading.Lock()
        # Guards activate_session against concurrent WS calls spawning duplicate workers
        self._activate_lock = threading.Lock()
        # Сериализация append к data/llm_log.jsonl (kimi-search-1 #5).
        self._llm_log_write_lock = threading.Lock()

    def _persist_llm_log(self, entry: dict):
        """Append-only JSONL write-through for LLM reply events (async via _schedule_save).
        Сериализуем через _llm_log_write_lock — иначе concurrent appends могут интерливить
        большие JSON-строки (>PIPE_BUF на Linux) и корраптить JSONL (kimi-search-1 #5).
        """
        def _write():
            try:
                line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
                with self._llm_log_write_lock:
                    with open(LLM_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(line)
            except Exception as e:
                log_debug(f"llm_log persist error: {e}")
        _schedule_save(_write)

    def _build_session_urls(self, resume_hash: str) -> list[str]:
        """URL поиска для браузерной сессии: resume-URL + keyword-URLs из глобального пула."""
        resume_url = f"{hh_base()}/search/vacancy?resume={resume_hash}&order_by=publication_time&items_on_page=20"
        urls = [resume_url]
        for item in CONFIG.url_pool:
            entry = _url_entry(item)
            if entry["url"] and "resume=" not in entry["url"]:
                urls.append(entry["url"])
        # Добавляем resume-URL в пул, если ещё нет
        pool_urls = [_url_entry(u)["url"] for u in CONFIG.url_pool]
        if resume_url not in pool_urls:
            CONFIG.url_pool.append({"url": resume_url, "pages": CONFIG.pages_per_url})
            save_config()
        return urls

    def activate_session(self, temp_idx: int) -> bool:
        """Запустить браузерную сессию как полноценный бот-аккаунт."""
        with self._activate_lock:
            if temp_idx < 0 or temp_idx >= len(self.temp_sessions):
                return False
            ts = self.temp_sessions[temp_idx]
            if not ts.get("resume_hash"):
                return False
            if temp_idx in self.temp_states:
                return True  # уже запущен
            acc = {
                "name": ts["name"],
                "short": ts.get("short", ts["name"]),
                "color": "yellow",
                "resume_hash": ts["resume_hash"],
                "letter": ts.get("letter", ""),
                "cookies": ts.get("cookies", {}),
                "urls": self._build_session_urls(ts["resume_hash"]),
                # Подтягиваем persistent флаги из temp_sessions — без этого
                # после restart browser-сессии теряли use_oauth/apply_tests (swarm-12 #9).
                "use_oauth": bool(ts.get("use_oauth", False)),
                "apply_tests": bool(ts.get("apply_tests", False)),
            }
            state = AccountState(acc)
            self.temp_states[temp_idx] = state
            ts["bot_active"] = True
        save_browser_sessions(self.temp_sessions)
        log_debug(f"activate_session({temp_idx}): starting threads...")
        t1 = threading.Thread(target=self._run_account_worker, args=(900 + temp_idx, state), daemon=True, name=f"worker-{temp_idx}")
        t2 = threading.Thread(target=self._fetch_hh_stats_worker, args=(900 + temp_idx, state), daemon=True, name=f"stats-{temp_idx}")
        t1.start()
        t2.start()
        log_debug(f"activate_session({temp_idx}): threads started t1={t1.is_alive()} t2={t2.is_alive()}")
        self._add_log(state.short, "yellow", f"\U0001f310 Сессия {ts['name']} запущена как бот", "success")
        return True

    def _get_apply_acc(self, idx: int) -> dict | None:
        """Вернуть acc dict для apply-эндпоинтов (обычный или временный аккаунт)"""
        if 0 <= idx < len(self.account_states):
            return dict(self.account_states[idx].acc)
        temp_idx = idx - len(self.account_states)
        if 0 <= temp_idx < len(self.temp_sessions):
            return dict(self.temp_sessions[temp_idx])
        return None

    def _get_apply_state(self, idx: int):
        """Вернуть AccountState или None для temp-сессий"""
        if 0 <= idx < len(self.account_states):
            return self.account_states[idx]
        return None

    def start(self):
        _load_cache()
        load_config()
        self._start_time = datetime.now()
        # Load recent responses from applied_vacancies into deque
        try:
            with _cache_lock:
                if _cache_applied:
                    all_items = []
                    for acc_name, vacancies in _cache_applied.items():
                        if isinstance(vacancies, dict):
                            for vid, info in vacancies.items():
                                if isinstance(info, dict):
                                    all_items.append({
                                        "id": vid, "title": info.get("title", ""),
                                        "company": info.get("company", ""),
                                        "time": (info.get("at", "") or "")[:16].replace("T", " "),
                                        "icon": "✅", "acc": acc_name,
                                    })
                    # Sort by time, take last 100
                    all_items.sort(key=lambda x: x.get("time", ""), reverse=True)
                    for item in all_items[:100]:
                        self.recent_responses.append(item)
                    log_debug(f"Loaded {len(self.recent_responses)} recent responses from cache")
        except Exception as e:
            log_debug(f"Failed to load recent responses: {e}")
        self.account_states = [AccountState(acc) for acc in accounts_data]
        for i, state in enumerate(self.account_states):
            t1 = threading.Thread(
                target=self._run_account_worker, args=(i, state), daemon=True
            )
            t2 = threading.Thread(
                target=self._fetch_hh_stats_worker, args=(i, state), daemon=True
            )
            t1.start()
            t2.start()
        # Авто-активация браузерных сессий, которые были запущены до перезапуска
        log_debug(f"start(): {len(self.temp_sessions)} temp sessions to check")
        for i, ts in enumerate(self.temp_sessions):
            log_debug(f"start(): session {i}: bot_active={ts.get('bot_active')}, resume_hash={bool(ts.get('resume_hash'))}")
            if ts.get("bot_active") and ts.get("resume_hash"):
                ts["paused"] = False  # Reset pause on startup
                try:
                    result = self.activate_session(i)
                    log_debug(f"start(): activate_session({i}) = {result}")
                except Exception as e:
                    log_debug(f"start(): activate_session({i}) ERROR: {e}")
        self._add_log("", "", "\U0001f680 Бот запущен", "success")

    def stop(self):
        self._stop_event.set()

    def toggle_pause(self):
        self.paused = not self.paused
        msg = "⏸️ Пауза" if self.paused else "▶️ Продолжение"
        level = "warning" if self.paused else "success"
        self._add_log("", "", msg, level)

    def toggle_account_pause(self, idx: int):
        state = None
        if 0 <= idx < len(self.account_states):
            state = self.account_states[idx]
        else:
            temp_idx = idx - len(self.account_states)
            state = self.temp_states.get(temp_idx)
        if not state:
            return
        with state._state_lock:
            state.paused = not state.paused
            if not state.paused:
                # Reset hard stop / limit so worker can continue
                state.hard_stopped = False
                state.limit_exceeded = False
                state.limit_reset_time = None
                # Иначе следующая ошибка снова auto-pause'нет account (state_machine #6).
                state.consecutive_errors = 0
                state.paused_reason = ""
            else:
                state.paused_reason = "manual"
        msg = (
            f"⏸️ Аккаунт {state.short} приостановлен"
            if state.paused
            else f"▶️ Аккаунт {state.short} возобновлён"
        )
        self._add_log(state.short, state.color, msg, "warning" if state.paused else "success")

    def toggle_account_llm(self, idx: int):
        state = None
        if 0 <= idx < len(self.account_states):
            state = self.account_states[idx]
        else:
            temp_idx = idx - len(self.account_states)
            state = self.temp_states.get(temp_idx)
        if state:
            state.llm_enabled = not state.llm_enabled
            msg = (
                f"\U0001f916 LLM включён для {state.short}"
                if state.llm_enabled
                else f"\U0001f916 LLM выключен для {state.short}"
            )
            self._add_log(state.short, state.color, msg, "info")

    def toggle_account_oauth(self, idx: int):
        state = None
        if 0 <= idx < len(self.account_states):
            state = self.account_states[idx]
        else:
            temp_idx = idx - len(self.account_states)
            state = self.temp_states.get(temp_idx)
        if state:
            state.use_oauth = not state.use_oauth
            mode = "\U0001f511 OAuth" if state.use_oauth else "\U0001f310 Web"
            self._add_log(state.short, state.color, f"{mode} откликов для {state.short}", "info")
            # Persist to account data
            state.acc["use_oauth"] = state.use_oauth
            if 0 <= idx < len(accounts_data):
                accounts_data[idx]["use_oauth"] = state.use_oauth
                save_accounts()
            else:
                temp_idx = idx - len(self.account_states)
                if 0 <= temp_idx < len(self.temp_sessions):
                    self.temp_sessions[temp_idx]["use_oauth"] = state.use_oauth
                    save_browser_sessions(self.temp_sessions)

    def trigger_resume_touch(self, idx: int):
        if 0 <= idx < len(self.account_states):
            self.account_states[idx].next_resume_touch = datetime.now()
        else:
            temp_idx = idx - len(self.account_states)
            if temp_idx in self.temp_states:
                self.temp_states[temp_idx].next_resume_touch = datetime.now()

    def toggle_resume_touch(self, idx: int) -> bool:
        state = None
        if 0 <= idx < len(self.account_states):
            state = self.account_states[idx]
        else:
            temp_idx = idx - len(self.account_states)
            if temp_idx in self.temp_states:
                state = self.temp_states[temp_idx]
        if state:
            state.resume_touch_enabled = not state.resume_touch_enabled
            return state.resume_touch_enabled
        return False

    def _add_log(self, acc_short: str, acc_color: str, message: str, level: str = "info", neg_id: str = ""):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "acc": acc_short,
            "color": acc_color,
            "message": message,
            "level": level,
        }
        if neg_id:
            entry["neg_id"] = str(neg_id)
        with self._deque_lock:
            self.activity_log.appendleft(entry)

    def _add_acc_event(self, state: AccountState, icon: str, etype: str,
                        title: str, company: str, extra: str = ""):
        with state._deque_lock:
            state.acc_event_log.appendleft({
                "time": datetime.now().strftime("%H:%M"),
                "icon": icon,
                "type": etype,
                "title": title[:45],
                "company": company[:25],
                "extra": extra[:70],
            })

    def _check_auto_pause(self, state: AccountState):
        """Авто-пауза при превышении лимита ошибок подряд."""
        n = CONFIG.auto_pause_errors
        if n > 0 and state.consecutive_errors >= n:
            with state._state_lock:
                # Не перетираем manual pause: если пользователь только что снял паузу,
                # `toggle_account_pause` обнулил `consecutive_errors`. Если он стоит на 0,
                # auto-pause не должен срабатывать заново.
                if state.consecutive_errors >= n and not state.paused:
                    state.paused = True
                    state.paused_reason = "auto_errors"
                    self._add_log(
                        state.short, state.color,
                        f"⛔ Авто-пауза: {n} ошибок подряд. Снимите вручную.",
                        "error",
                    )

    def _maybe_roll_daily_counter(self, state: AccountState) -> bool:
        today = _today_msk()
        with state._state_lock:
            if state.daily_date != today:
                state.daily_sent = 0
                state.daily_date = today
                state.hard_stopped = False
                # Сбрасываем и limit-флаги: иначе после rollover остаёмся в limit-check
                # block с уже обнулённым счётчиком (kimi-search-1 #9).
                state.limit_exceeded = False
                state.limit_reset_time = None
                # Сбрасываем paused если он был auto/limit (kimi-search-1 #9 extra) — но НЕ manual.
                if state.paused and state.paused_reason in ("limit", "auto_errors"):
                    state.paused = False
                    state.paused_reason = ""
                    # Также сбрасываем счётчик ошибок — иначе следующая ошибка
                    # сразу re-pause'нет аккаунт (consistency с toggle_account_pause).
                    state.consecutive_errors = 0
                return True
        return False

    def _add_response(
        self,
        state: AccountState,
        vid: str,
        title: str,
        company: str,
        result: str,
        salary: str = "",
    ):
        result_icons = {
            "sent": "✅",
            "test": "\U0001f9ea",
            "already": "\U0001f504",
            "limit": "\U0001f6ab",
            "error": "❌",
        }
        self.recent_responses.appendleft({
            "time": datetime.now().strftime("%H:%M:%S"),
            "acc": state.short,
            "color": state.color,
            "id": vid,
            "title": title,
            "company": company,
            "salary": salary,
            "result": result,
            "icon": result_icons.get(result, "❓"),
        })

    def get_state_snapshot(self) -> dict:
        """Full JSON snapshot for WS broadcast"""
        now = datetime.now()
        uptime = int((now - self._start_time).total_seconds()) if self._start_time else 0

        # All states: regular + temp sessions (for global_stats, vacancy_queues)
        all_states = list(self.account_states) + list(self.temp_states.values())

        accounts = []
        for i, s in enumerate(self.account_states):
            next_touch_str = ""
            if s.next_resume_touch:
                rem = (s.next_resume_touch - now).total_seconds()
                if rem > 0:
                    h = int(rem // 3600)
                    m = int((rem % 3600) // 60)
                    next_touch_str = f"{s.next_resume_touch.strftime('%H:%M')} ({h}ч{m}м)"
                else:
                    next_touch_str = "сейчас!"

            hh_updated_str = ""
            if s.hh_stats_updated:
                ago = int((now - s.hh_stats_updated).total_seconds() / 60)
                hh_updated_str = (
                    f"{ago}м назад" if ago < 60 else f"{ago // 60}ч{ago % 60}м назад"
                )

            with s._state_lock:
                _status = s.status
                _status_detail = s.status_detail
                _hh_interviews = s.hh_interviews
                _hh_interviews_recent = s.hh_interviews_recent
                _hh_viewed = s.hh_viewed
                _hh_discards = s.hh_discards
                _hh_not_viewed = s.hh_not_viewed
                _hh_unread_by_employer = s.hh_unread_by_employer
                _hh_interviews_list = s.hh_interviews_list[:20]
                _current_vacancy_idx = s.current_vacancy_idx
                _total_vacancies = s.total_vacancies

            with _cache_lock:
                _total_applied = len((_cache_applied or {}).get(s.name, {}))

            accounts.append({
                "idx": i,
                "name": s.name,
                "short": s.short,
                "color": s.color,
                "status": _status,
                "status_detail": _status_detail,
                "sent": s.sent,
                "total_applied": _total_applied,
                "tests": s.tests,
                "errors": s.errors,
                "already_applied": s.already_applied,
                "found_vacancies": s.found_vacancies,
                "current_vacancy_title": s.current_vacancy_title,
                "current_vacancy_company": s.current_vacancy_company,
                "current_vacancy_idx": _current_vacancy_idx,
                "total_vacancies": _total_vacancies,
                "salary_skipped": s.salary_skipped,
                "questionnaire_sent": s.questionnaire_sent,
                "limit_exceeded": s.limit_exceeded,
                "paused": s.paused,
                "next_resume_touch": next_touch_str,
                "resume_touch_status": s.resume_touch_status,
                "resume_touch_enabled": s.resume_touch_enabled,
                "letter": s.acc.get("letter", ""),
                "urls": s.acc.get("urls", []),
                "url_pages": s.acc.get("url_pages", {}),
                "hh_interviews": _hh_interviews,
                "hh_interviews_recent": _hh_interviews_recent,
                "hh_viewed": _hh_viewed,
                "hh_discards": _hh_discards,
                "hh_not_viewed": _hh_not_viewed,
                "hh_unread_by_employer": _hh_unread_by_employer,
                "hh_stats_updated": hh_updated_str,
                "hh_stats_loading": s.hh_stats_loading,
                "hh_interviews_list": _hh_interviews_list,
                "hh_possible_offers": s.hh_possible_offers[:10],
                "action_history": list(s.action_history),
                "resume_views_7d": s.resume_views_7d,
                "resume_views_new": s.resume_views_new,
                "resume_shows_7d": s.resume_shows_7d,
                "resume_invitations_7d": s.resume_invitations_7d,
                "resume_invitations_new": s.resume_invitations_new,
                "resume_next_touch_seconds": s.resume_next_touch_seconds,
                "resume_free_touches": s.resume_free_touches,
                "resume_global_invitations": s.resume_global_invitations,
                "resume_new_invitations_total": s.resume_new_invitations_total,
                "acc_event_log": list(s.acc_event_log),
                "apply_tests": s.apply_tests,
                "consecutive_errors": s.consecutive_errors,
                "url_stats": dict(s.url_stats),
                "cookies_expired": s.cookies_expired,
                "oauth_status": get_oauth_status(s.acc.get("resume_hash", "")),
                "llm_enabled": s.llm_enabled,
                "llm_status": s.llm_status,
                "llm_replied_count": s.llm_replied_count,
                "llm_pending_chats": s.llm_pending_chats,
                "use_oauth": s.use_oauth,
                "daily_sent": s.daily_sent,
                "daily_limit": CONFIG.daily_apply_limit,
                "hard_stopped": s.hard_stopped,
            })

        # Temp browser sessions — append after regular accounts
        base_idx = len(self.account_states)
        for i, ts in enumerate(self.temp_sessions):
            idx = base_idx + i
            state = self.temp_states.get(i)
            if state:
                # Активная сессия — реальные данные из AccountState
                s = state
                nrt = s.next_resume_touch.strftime("%H:%M") if s.next_resume_touch else ""
                ts_hh_updated_str = ""
                if s.hh_stats_updated:
                    ago = int((now - s.hh_stats_updated).total_seconds() / 60)
                    ts_hh_updated_str = (
                        f"{ago}м назад" if ago < 60 else f"{ago // 60}ч{ago % 60}м назад"
                    )
                with s._state_lock:
                    _status = s.status
                    _status_detail = s.status_detail
                    _hh_interviews = s.hh_interviews
                    _hh_interviews_recent = s.hh_interviews_recent
                    _hh_viewed = s.hh_viewed
                    _hh_discards = s.hh_discards
                    _hh_not_viewed = s.hh_not_viewed
                    _hh_unread_by_employer = s.hh_unread_by_employer
                    _hh_interviews_list = s.hh_interviews_list[:20]
                    _current_vacancy_idx = s.current_vacancy_idx
                    _total_vacancies = s.total_vacancies

                with _cache_lock:
                    _total_applied = len((_cache_applied or {}).get(s.acc["name"], {}))

                accounts.append({
                    "idx": idx,
                    "name": s.acc["name"],
                    "short": s.acc.get("short", ""),
                    "color": "yellow",
                    "temp": True,
                    "bot_active": True,
                    "resume_hash": s.acc.get("resume_hash", ""),
                    "letter": s.acc.get("letter", ""),
                    "urls": s.acc.get("urls", []),
                    "url_pages": s.acc.get("url_pages", {}),
                    "status": _status,
                    "status_detail": _status_detail,
                    "sent": s.sent,
                    "total_applied": _total_applied,
                    "tests": s.tests,
                    "errors": s.errors,
                    "already_applied": s.already_applied,
                    "found_vacancies": s.found_vacancies,
                    "current_vacancy_title": s.current_vacancy_title,
                    "current_vacancy_company": s.current_vacancy_company,
                    "current_vacancy_idx": _current_vacancy_idx,
                    "total_vacancies": _total_vacancies,
                    "salary_skipped": s.salary_skipped,
                    "questionnaire_sent": s.questionnaire_sent,
                    "limit_exceeded": s.limit_exceeded,
                    "paused": s.paused,
                    "next_resume_touch": nrt,
                    "resume_touch_status": s.resume_touch_status,
                    "resume_touch_enabled": s.resume_touch_enabled,
                    "hh_interviews": _hh_interviews,
                    "hh_interviews_recent": _hh_interviews_recent,
                    "hh_viewed": _hh_viewed,
                    "hh_discards": _hh_discards,
                    "hh_not_viewed": _hh_not_viewed,
                    "hh_unread_by_employer": _hh_unread_by_employer,
                    "hh_stats_updated": ts_hh_updated_str,
                    "hh_stats_loading": s.hh_stats_loading,
                    "hh_interviews_list": _hh_interviews_list,
                    "hh_possible_offers": s.hh_possible_offers[:10],
                    "action_history": list(s.action_history),
                    "resume_views_7d": s.resume_views_7d,
                    "resume_views_new": s.resume_views_new,
                    "resume_shows_7d": s.resume_shows_7d,
                    "resume_invitations_7d": s.resume_invitations_7d,
                    "resume_invitations_new": s.resume_invitations_new,
                    "resume_next_touch_seconds": s.resume_next_touch_seconds,
                    "resume_free_touches": s.resume_free_touches,
                    "resume_global_invitations": s.resume_global_invitations,
                    "resume_new_invitations_total": s.resume_new_invitations_total,
                    "acc_event_log": list(s.acc_event_log),
                    "apply_tests": s.apply_tests,
                    "consecutive_errors": s.consecutive_errors,
                    "url_stats": dict(s.url_stats),
                    "cookies_expired": s.cookies_expired,
                    "oauth_status": get_oauth_status(s.acc.get("resume_hash", "")),
                    "llm_enabled": s.llm_enabled,
                    "use_oauth": s.use_oauth,
                    "daily_sent": s.daily_sent,
                    "daily_limit": CONFIG.daily_apply_limit,
                    "hard_stopped": s.hard_stopped,
                })
            else:
                # Неактивная сессия — заглушка
                accounts.append({
                    "idx": idx,
                    "name": ts.get("name", f"Браузер #{i+1}"),
                    "short": ts.get("short", f"Браузер#{i+1}"),
                    "color": "yellow",
                    "temp": True,
                    "bot_active": False,
                    "resume_hash": ts.get("resume_hash", ""),
                    "all_resumes": ts.get("all_resumes", []),
                    "letter": ts.get("letter", ""),
                    "status": "—", "status_detail": "", "sent": 0, "tests": 0,
                    "errors": 0, "already_applied": 0, "found_vacancies": 0,
                    "current_vacancy_title": "", "current_vacancy_company": "",
                    "current_vacancy_idx": 0, "total_vacancies": 0,
                    "salary_skipped": 0, "questionnaire_sent": 0,
                    "limit_exceeded": False, "paused": False,
                    "next_resume_touch": "", "resume_touch_status": "",
                    "hh_interviews": 0, "hh_viewed": 0, "hh_discards": 0,
                    "hh_not_viewed": 0, "hh_unread_by_employer": 0,
                    "hh_stats_updated": "", "hh_stats_loading": False,
                    "hh_interviews_list": [], "hh_possible_offers": [], "action_history": [],
                    "resume_views_7d": 0, "resume_views_new": 0, "resume_shows_7d": 0,
                    "resume_invitations_7d": 0, "resume_invitations_new": 0,
                    "resume_next_touch_seconds": 0, "resume_free_touches": 0,
                    "resume_global_invitations": 0, "resume_new_invitations_total": 0,
                    "acc_event_log": [],
                    "apply_tests": bool(ts.get("apply_tests", False)),
                    "consecutive_errors": 0,
                    "url_stats": {},
                    "cookies_expired": False,
                    "llm_enabled": True,
                    "use_oauth": bool(ts.get("use_oauth", False)),
                    "daily_sent": 0,
                    "daily_limit": CONFIG.daily_apply_limit,
                    "hard_stopped": False,
                })

        storage_stats = get_stats()

        _vacancy_queues = {}
        for s in all_states:
            with s._state_lock:
                _current_vacancy_idx = s.current_vacancy_idx
                _vacancies_queue = list(s.vacancies_queue)
            _vacancy_queues[s.short] = {
                "remaining": max(0, len(_vacancies_queue) - _current_vacancy_idx),
                "next": _vacancies_queue[_current_vacancy_idx: _current_vacancy_idx + 5]
                if _vacancies_queue
                else [],
            }

        return {
            "type": "state_update",
            "uptime_seconds": uptime,
            "paused": self.paused,
            "accounts": accounts,
            "recent_responses": list(self.recent_responses),
            "log": list(self.activity_log),
            "llm_log": list(self.llm_log),
            "config": {
                "pages_per_url": CONFIG.pages_per_url,
                "response_delay": CONFIG.response_delay,
                "pause_between_cycles": CONFIG.pause_between_cycles,
                "batch_responses": CONFIG.batch_responses,
                "limit_check_interval": CONFIG.limit_check_interval,
                "min_salary": CONFIG.min_salary,
                "auto_pause_errors": CONFIG.auto_pause_errors,
                "auto_apply_tests": CONFIG.auto_apply_tests,
                "use_oauth_apply": CONFIG.use_oauth_apply,
                "daily_apply_limit": CONFIG.daily_apply_limit,
                "stop_on_hh_limit": CONFIG.stop_on_hh_limit,
                "llm_check_interval": CONFIG.llm_check_interval,
                "allowed_schedules": CONFIG.allowed_schedules,
                "title_include_keywords": getattr(CONFIG, "title_include_keywords", []),
                "title_exclude_keywords": getattr(CONFIG, "title_exclude_keywords", []),
                "questionnaire_templates": CONFIG.questionnaire_templates,
                "questionnaire_default_answer": questionnaire_default_answer(),
                "letter_templates": CONFIG.letter_templates,
                "url_pool": CONFIG.url_pool,
                "skip_inconsistent": CONFIG.skip_inconsistent,
                "filter_agencies": CONFIG.filter_agencies,
                "filter_low_competition": CONFIG.filter_low_competition,
                "search_period_days": CONFIG.search_period_days,
                "llm_enabled": CONFIG.llm_enabled,
                "llm_auto_send": CONFIG.llm_auto_send,
                "llm_fill_questionnaire": CONFIG.llm_fill_questionnaire,
                "llm_use_cover_letter": CONFIG.llm_use_cover_letter,
                "llm_use_resume": CONFIG.llm_use_resume,
                "llm_model": CONFIG.llm_model,
                "llm_base_url": CONFIG.llm_base_url,
                # Системный промпт нужен в снимке: после релоада фронт инитит
                # textarea дефолтом, а потом любая правка ругого поля LLM
                # autosave'ила бы этот дефолт обратно на диск. Снимок служит
                # источником истины для UI.
                "llm_system_prompt": CONFIG.llm_system_prompt,
                # Note: don't include llm_api_key in snapshot for security,
                # но кладём fingerprint + key_set, чтобы UI мог показать
                # «✓ ключ сохранён (sk-p…wxyz, 164 симв.)» после релоада —
                # type=password input не покажет значение даже если бы оно было.
                "llm_api_key_set": bool((CONFIG.llm_api_key or "").strip()),
                "llm_api_key_fingerprint": _fingerprint_key(CONFIG.llm_api_key),
                "llm_profiles": [
                    {
                        "name": p.get("name", ""),
                        "base_url": p.get("base_url", ""),
                        "model": p.get("model", ""),
                        "enabled": p.get("enabled", True),
                        "key_set": bool((p.get("api_key") or "").strip()),
                        "key_fingerprint": _fingerprint_key(p.get("api_key", "")),
                        "key_len": len((p.get("api_key") or "").strip()),
                    }
                    for p in (CONFIG.llm_profiles or [])
                ],
                "llm_profile_mode": CONFIG.llm_profile_mode,
            },
            "global_stats": {
                "total_sent": sum(s.sent for s in all_states),
                "total_tests": sum(s.tests for s in all_states),
                "total_errors": sum(s.errors for s in all_states),
                "total_found": sum(s.found_vacancies for s in all_states),
                "storage_total": storage_stats["total"],
                "storage_tests": storage_stats["tests"],
            },
            "vacancy_queues": _vacancy_queues,
        }

    def _run_account_worker(self, idx: int, state: AccountState) -> None:
        """Thread worker for an account — auto-restarts on crash"""
        while not self._stop_event.is_set() and not getattr(state, '_deleted', False):
            try:
                self._run_account_worker_inner(idx, state)
                break  # normal exit
            except Exception as e:
                log_exception(f"WORKER CRASHED [{state.short}]", e)
                state.status = "error"
                state.status_detail = f"Перезапуск через 30с ({str(e)[:30]})"
                self._add_log(state.short, state.color, f"⚠️ Worker упал: {str(e)[:50]}. Перезапуск через 30с", "error")
                time.sleep(30)
                state.status = "idle"
                state.status_detail = "Перезапущен после ошибки"
                self._add_log(state.short, state.color, "\U0001f504 Worker перезапущен", "info")

    def _run_account_worker_inner(self, idx: int, state: AccountState) -> None:
        acc = state.acc

        while not self._stop_event.is_set() and not state._deleted:
            # Global + per-account pause
            while (self.paused or state.paused) and not self._stop_event.is_set() and not state._deleted:
                # Auto-reset daily limit pause when new day starts
                if state.hard_stopped:
                    if self._maybe_roll_daily_counter(state):
                        # Не снимаем manual pause — если юзер сам остановил аккаунт,
                        # midnight-rollover не должен его перезапускать (swarm-12 #8).
                        if state.paused_reason != "manual":
                            state.paused = False
                            state.paused_reason = ""
                        state.limit_exceeded = False
                        state.limit_reset_time = None
                        state.status = "idle"
                        state.status_detail = "Новый день — лимит сброшен"
                        self._add_log(state.short, state.color,
                            "\U0001f305 Новый день! Лимит сброшен" + (
                                "" if state.paused_reason != "manual" else ", аккаунт остался на manual pause"),
                            "success")
                        break
                if state.hard_stopped:
                    state.status = "limit"
                    if CONFIG.daily_apply_limit > 0 and state.daily_sent >= CONFIG.daily_apply_limit:
                        state.status_detail = f"Дневной лимит: {state.daily_sent}/{CONFIG.daily_apply_limit}. Сброс завтра в 00:00"
                    else:
                        state.status_detail = "Лимит HH. Сброс завтра в 00:00"
                elif state.limit_exceeded:
                    state.status = "limit"
                    if state.limit_reset_time:
                        remaining = int((state.limit_reset_time - datetime.now()).total_seconds())
                        if remaining > 0:
                            state.status_detail = f"Лимит HH. Проверка через {remaining // 60}м{remaining % 60:02d}с"
                        else:
                            state.status_detail = "Лимит HH. Проверка сейчас..."
                    else:
                        state.status_detail = "Лимит HH. Проверка через 1м"
                else:
                    state.status = "idle"
                    state.status_detail = "Пауза пользователем"
                time.sleep(1)

            if self._stop_event.is_set():
                break

            now = datetime.now()

            # === АВТОПОДНЯТИЕ РЕЗЮМЕ ===
            if state.resume_touch_enabled:
                should_touch = False
                if state.next_resume_touch is None:
                    should_touch = True
                elif now >= state.next_resume_touch:
                    should_touch = True

                if should_touch:
                    self._add_log(state.short, state.color, "\U0001f4e4 Поднимаю резюме...", "info")
                    success, message = touch_resume(acc)

                    if success:
                        state.resume_touch_status = "✅ Поднято!"
                        state.next_resume_touch = now + timedelta(hours=4)
                        self._add_log(
                            state.short, state.color,
                            f"✅ Резюме поднято! Следующее в {state.next_resume_touch.strftime('%H:%M')}",
                            "success",
                        )
                    else:
                        state.resume_touch_status = f"⏳ {message}"
                        state.next_resume_touch = now + timedelta(hours=4)
                        self._add_log(
                            state.short, state.color,
                            f"\U0001f4e4 {message}. Повтор в {state.next_resume_touch.strftime('%H:%M')}",
                            "warning",
                        )

            # === ПРОВЕРКА ЛИМИТА ===
            if state.limit_exceeded:
                # If no reset time set, schedule a check soon
                if not state.limit_reset_time:
                    state.limit_reset_time = now + timedelta(minutes=1)

                if now >= state.limit_reset_time:
                    state.status = "checking"
                    state.status_detail = "Проверка сброса лимита..."
                    self._add_log(state.short, state.color, "\U0001f50d Проверяю сброс лимита...", "info")

                    if not check_limit(acc):
                        state.limit_exceeded = False
                        state.limit_reset_time = None
                        state.paused = False
                        state.hard_stopped = False
                        state.status_detail = ""
                        self._add_log(
                            state.short, state.color, "✅ Лимит сброшен! Продолжаю работу", "success"
                        )
                    else:
                        state.limit_reset_time = now + timedelta(minutes=CONFIG.limit_check_interval)
                        state.status = "limit"
                        state.status_detail = f"Проверка в {state.limit_reset_time.strftime('%H:%M')}"
                        self._add_log(
                            state.short, state.color,
                            f"⏳ Лимит ещё активен, попробую в {state.limit_reset_time.strftime('%H:%M')}",
                            "warning",
                        )
                        time.sleep(60)
                        continue
                else:
                    state.status = "limit"
                    remaining = int((state.limit_reset_time - now).total_seconds())
                    state.status_detail = f"Проверка через {remaining}с"
                    time.sleep(30)
                    continue

            # === СБОР ВАКАНСИЙ (ПАРАЛЛЕЛЬНО) ===
            # Если у аккаунта нет своих URL — используем глобальный пул
            effective_urls = acc.get("urls") or [_url_entry(u)["url"] for u in CONFIG.url_pool]
            state.total_urls = len(effective_urls)

            state.status = "collecting"
            state.status_detail = "Начинаю параллельный сбор..."
            state.vacancies_by_url = {}
            state.vacancy_meta = {}  # Сброс метаданных вакансий для нового цикла

            self._add_log(
                state.short, state.color,
                f"\U0001f4e5 Параллельный сбор: {len(effective_urls)} URL × {CONFIG.pages_per_url} стр",
                "info",
            )

            try:
                results_by_url, salary_map, schedule_map = asyncio.run(self._collect_all_urls_parallel(state))
            except Exception as e:
                log_exception(f"COLLECT CRASH [{state.short}]", e)
                state.status = "error"
                state.status_detail = f"Ошибка сбора: {str(e)[:50]}"
                time.sleep(60)
                continue

            all_vacancies = []
            for url in effective_urls:
                url_vacancies = results_by_url.get(url, set())
                state.vacancies_by_url[url] = len(url_vacancies)
                all_vacancies.extend(url_vacancies)

                query = extract_search_query(url)
                if url_vacancies:
                    self._add_log(state.short, state.color, f"\U0001f4ca {query}: {len(url_vacancies)}", "info")
            # Сохраняем статистику по URL для снапшота
            state.url_stats = dict(state.vacancies_by_url)

            unique_vacancies = set(all_vacancies)
            total_collected = len(unique_vacancies)

            self._add_log(
                state.short, state.color,
                f"\U0001f4ca Всего собрано: {len(all_vacancies)} ({total_collected} уникальных)",
                "info",
            )

            if not unique_vacancies:
                if state.cookies_expired:
                    state.paused = True
                    state.paused_reason = "auth"
                    self._add_log(
                        state.short, state.color,
                        "⚠️ Куки протухли! Обновите куки и снимите паузу.", "error",
                    )
                    self._add_acc_event(state, "⚠️", "error", "Авторизация", "", "Обновите куки")
                    continue
                state.status = "waiting"
                state.status_detail = "Нет вакансий"
                self._add_log(
                    state.short, state.color,
                    "⚠️ Не найдено ни одной вакансии, пауза 2 мин",
                    "warning",
                )
                time.sleep(120)
                continue

            # Фильтрация
            filtered = []
            already_count = 0
            test_count = 0
            salary_skipped = 0
            schedule_skipped = 0
            title_skipped = 0
            apply_tests = state.apply_tests or CONFIG.auto_apply_tests
            title_include_keywords = [
                str(k).strip().lower()
                for k in getattr(CONFIG, "title_include_keywords", [])
                if str(k).strip()
            ]
            title_exclude_keywords = [
                str(k).strip().lower()
                for k in getattr(CONFIG, "title_exclude_keywords", [])
                if str(k).strip()
            ]

            for vid in unique_vacancies:
                meta = state.vacancy_meta.get(vid, {})
                title = (meta.get("title") or "").lower()
                if title:
                    if title_include_keywords and not any(k in title for k in title_include_keywords):
                        title_skipped += 1
                        continue
                    if title_exclude_keywords and any(k in title for k in title_exclude_keywords):
                        title_skipped += 1
                        continue
                if is_applied(acc["name"], vid):
                    already_count += 1
                    state.already_applied += 1
                elif (is_test(vid) or state._test_failures.get(vid, 0) >= 2) and not apply_tests:
                    test_count += 1
                    state.tests += 1
                elif CONFIG.allowed_schedules:
                    sched = schedule_map.get(vid, set())
                    if sched and not sched.intersection(CONFIG.allowed_schedules):
                        schedule_skipped += 1
                    elif CONFIG.min_salary > 0:
                        sal = salary_map.get(vid)
                        if sal is None or sal < CONFIG.min_salary:
                            salary_skipped += 1
                            state.salary_skipped += 1
                        else:
                            filtered.append(vid)
                    else:
                        filtered.append(vid)
                elif CONFIG.min_salary > 0:
                    sal = salary_map.get(vid)
                    if sal is None or sal < CONFIG.min_salary:
                        salary_skipped += 1
                        state.salary_skipped += 1
                    else:
                        filtered.append(vid)
                else:
                    filtered.append(vid)

            sal_msg = f", \U0001f4b0 зарплата {salary_skipped}" if CONFIG.min_salary > 0 else ""
            sched_msg = f", \U0001f3e2 формат {schedule_skipped}" if CONFIG.allowed_schedules else ""
            title_msg = f", \U0001f3f7️ заголовок {title_skipped}" if title_skipped else ""
            self._add_log(
                state.short, state.color,
                f"\U0001f50d Фильтрация: ✅ уже {already_count}, \U0001f9ea тест {test_count}{sal_msg}{sched_msg}{title_msg}, \U0001f195 новые {len(filtered)}",
                "info",
            )

            if not filtered:
                state.status = "waiting"
                state.status_detail = "Нет новых вакансий"
                self._add_log(
                    state.short, state.color,
                    f"⚠️ Все вакансии уже обработаны ({already_count} откликов, {test_count} тестов), пауза 2 мин",
                    "warning",
                )
                time.sleep(120)
                continue

            random.shuffle(filtered)

            # Hot leads priority: fetch possible_job_offers and put matching vacancies first
            try:
                r_offers = requests.get(
                    hh_base() + "/shards/applicant/negotiations/possible_job_offers",
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "application/json",
                        "X-Xsrftoken": acc.get("cookies", {}).get("_xsrf", ""),
                        "Referer": hh_base() + "/applicant/negotiations",
                    },
                    cookies=acc.get("cookies", {}), timeout=10,
                )
                if r_offers.status_code == 200:
                    offers_data = r_offers.json()
                    offer_items = offers_data if isinstance(offers_data, list) else offers_data.get("possibleJobOffers", [])
                    offer_vids = set()
                    for o in offer_items:
                        vid_val = o.get("vacancyId", "")
                        if vid_val:
                            offer_vids.add(str(vid_val))
                    if offer_vids:
                        hot = [v for v in filtered if v in offer_vids]
                        cold = [v for v in filtered if v not in offer_vids]
                        filtered = hot + cold
                        if hot:
                            self._add_log(state.short, state.color,
                                f"\U0001f525 {len(hot)} горячих лидов в начале очереди", "success")
            except Exception:
                pass

            state.vacancies_queue = filtered
            state.total_vacancies = len(filtered)
            state.found_vacancies += len(all_vacancies)

            self._add_log(
                state.short, state.color,
                f"✅ Найдено {len(filtered)} новых вакансий для отклика!",
                "success",
            )
            self.vacancy_queues[state.short] = {
                "vacancies": filtered,
                "current": 0,
                "color": state.color,
            }

            # === ОТПРАВКА ОТКЛИКОВ (ПАКЕТАМИ) ===
            state.status = "applying"
            state.status_detail = f"0/{state.total_vacancies}"

            batch_size = CONFIG.batch_responses
            i = 0

            while i < len(filtered):
                if self._stop_event.is_set() or self.paused or state.paused or state.limit_exceeded:
                    break

                batch = filtered[i: i + batch_size]
                state.current_vacancy_idx = i + 1
                state.status_detail = (
                    f"{i + 1}-{min(i + batch_size, len(filtered))}/{state.total_vacancies}"
                )

                if state.short in self.vacancy_queues:
                    self.vacancy_queues[state.short]["current"] = i

                # Daily limit check
                if self._maybe_roll_daily_counter(state):
                    # Cleanup unbounded dicts on new day
                    if len(state._test_failures) > 500:
                        state._test_failures.clear()
                    if len(state._msg_consecutive) > 500:
                        state._msg_consecutive.clear()
                if CONFIG.daily_apply_limit > 0 and state.daily_sent >= CONFIG.daily_apply_limit:
                    state.hard_stopped = True
                    state.paused = True
                    state.paused_reason = "limit"  # чтобы midnight-rollover мог снять
                    state.status = "limit"
                    state.status_detail = f"Дневной лимит: {state.daily_sent}/{CONFIG.daily_apply_limit}. Сброс завтра в 00:00"
                    self._add_log(state.short, state.color,
                        f"\U0001f6d1 Дневной лимит {CONFIG.daily_apply_limit} откликов. Пауза до завтра 00:00.", "error")
                    break

                # Pre-check: skip inconsistent vacancies if enabled
                if CONFIG.skip_inconsistent:
                    checked_batch = []
                    for vid in batch:
                        precheck = _check_vacancy_before_apply(acc, vid)
                        if not precheck["ok"]:
                            meta = state.vacancy_meta.get(vid, {})
                            display_title = (meta.get("title") or vid)[:40]
                            self._add_log(state.short, state.color,
                                f"⏭ {display_title}: пропуск ({precheck['reason']})", "warning")
                        else:
                            checked_batch.append(vid)
                            # Collect HR contact info if available
                            contact = precheck.get("contact")
                            if contact and (contact.get("email") or contact.get("fio")):
                                meta = state.vacancy_meta.get(vid, {})
                                entry = {
                                    "vacancy_id": vid,
                                    "title": meta.get("title", ""),
                                    "company": meta.get("company", ""),
                                    "fio": contact.get("fio", ""),
                                    "email": contact.get("email", ""),
                                    "phone": contact.get("phone", ""),
                                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                    "account": state.short,
                                }
                                with self._hr_contacts_lock:
                                    if len(self.hr_contacts) < 500:
                                        self.hr_contacts.append(entry)
                    batch = checked_batch
                    if not batch:
                        i += batch_size
                        continue

                if len(batch) > 1:
                    self._add_log(
                        state.short, state.color,
                        f"\U0001f4e4 Пакет {len(batch)} откликов: {', '.join(batch[:3])}{'...' if len(batch) > 3 else ''}",
                        "info",
                    )

                # Choose apply method: OAuth API or Web (per-account or global)
                if state.use_oauth or CONFIG.use_oauth_apply:
                    # OAuth: synchronous, one by one (API doesn't support batch)
                    results = []
                    for vid in batch:
                        try:
                            result = _oauth_apply(acc, vid, acc.get("letter", ""))
                            results.append(result)
                        except Exception as e:
                            results.append(e)
                        if CONFIG.response_delay > 0:
                            time.sleep(CONFIG.response_delay)
                else:
                    # Web: async batch via aiohttp
                    def _make_send_batch(b):
                        async def send_batch():
                            tasks = [send_response_async(acc, vid) for vid in b]
                            return await asyncio.gather(*tasks, return_exceptions=True)
                        return send_batch
                    results = asyncio.run(_make_send_batch(batch)())

                for j, (vid, result_data) in enumerate(zip(batch, results)):
                    # Если auto-pause сработал на предыдущей итерации —
                    # не продолжаем отправлять оставшиеся вакансии (swarm-12 #10).
                    if state.paused or state.hard_stopped:
                        break
                    if isinstance(result_data, Exception):
                        state.errors += 1
                        state.consecutive_errors += 1
                        err_msg = str(result_data)[:60]
                        self._add_log(state.short, state.color, f"❌ {vid}: {err_msg}", "error")
                        self._add_acc_event(state, "❌", "error", vid, "", err_msg)
                        self._check_auto_pause(state)
                        continue

                    result, info = result_data

                    if result == "sent":
                        state.sent += 1
                        # Daily counter
                        self._maybe_roll_daily_counter(state)
                        state.daily_sent += 1
                        state.consecutive_errors = 0  # сброс счётчика ошибок
                        # Дополняем info мета-данными из поиска если API не вернул title
                        if not info.get("title"):
                            meta_fb = state.vacancy_meta.get(vid, {})
                            info = {**meta_fb, **info}
                        add_applied(acc["name"], vid, info)

                        # Collect HR contact if available
                        contact = info.get("contact", {})
                        if contact and (contact.get("email") or contact.get("fio")):
                            with self._hr_contacts_lock:
                                if len(self.hr_contacts) < 500:
                                    self.hr_contacts.append({
                                        "vacancy_id": vid,
                                        "title": info.get("title", ""),
                                        "company": info.get("company", ""),
                                        "fio": contact.get("fio", ""),
                                        "email": contact.get("email", ""),
                                        "phone": contact.get("phone", ""),
                                        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                        "acc": state.short,
                                    })

                        title = info.get("title", "Неизвестно")
                        company = info.get("company", "?")
                        sal_from = info.get("salary_from")
                        sal_to = info.get("salary_to")
                        salary = ""
                        if sal_from or sal_to:
                            salary = f"{sal_from or '?'} - {sal_to or '?'}"

                        state.current_vacancy_title = title
                        state.current_vacancy_company = company
                        state.action_history.append(f"✅ {title[:30]}")

                        self._add_response(state, vid, title, company, "sent", salary)
                        self._add_log(
                            state.short, state.color,
                            f"✅ {title[:40]} @ {company[:20]}",
                            "success",
                        )
                        self._add_acc_event(state, "✅", "sent", title or vid, company,
                                            salary if salary else "")

                    elif result == "test":
                        title = info.get("title", "")
                        company = info.get("company", "")
                        display_title = title[:40] if title else vid

                        if not (state.apply_tests or CONFIG.auto_apply_tests):
                            # Откликаться на тесты выключено — пропускаем
                            state.tests += 1
                            add_test_vacancy(vid, title, company,
                                             acc["name"], acc.get("resume_hash", ""))
                            state.action_history.append(f"⏭️ {display_title[:25]}")
                            self._add_response(state, vid, title, company, "test")
                            self._add_log(state.short, state.color,
                                          f"⏭️ Тест пропущен: {display_title}", "info")
                            self._add_acc_event(state, "⏭️", "test_skip",
                                                title or vid, company, "пропущено")
                        else:
                            # Пробуем автозаполнить опрос
                            q_result, q_info = asyncio.run(fill_and_submit_questionnaire(
                                acc, vid, vacancy_title=title, company=company))
                            if q_result == "sent":
                                state.sent += 1
                                state.questionnaire_sent += 1
                                state.consecutive_errors = 0
                                # Daily counter
                                self._maybe_roll_daily_counter(state)
                                state.daily_sent += 1
                                state.current_vacancy_title = title
                                state.current_vacancy_company = company
                                state.action_history.append(f"\U0001f4dd {display_title[:25]}")
                                self._add_response(state, vid, title, company, "sent")
                                self._add_log(state.short, state.color,
                                              f"\U0001f4dd Опрос пройден: {display_title}", "success")
                                q_info_full = {**state.vacancy_meta.get(vid, {}), **info}
                                add_applied(acc["name"], vid, q_info_full)
                                answer_preview = questionnaire_default_answer()[:50]
                                self._add_acc_event(state, "\U0001f4dd", "questionnaire",
                                                    title or vid, company,
                                                    f"Ответ: {answer_preview}")
                            elif q_result == "limit":
                                state.limit_exceeded = True
                                state.limit_reset_time = datetime.now() + timedelta(
                                    minutes=CONFIG.limit_check_interval
                                )
                                state.status = "limit"
                                state.status_detail = f"Проверка в {state.limit_reset_time.strftime('%H:%M')}"
                                self._add_log(state.short, state.color,
                                              f"\U0001f6ab ЛИМИТ при опросе! Повторная попытка в {state.limit_reset_time.strftime('%H:%M')}",
                                              "error")
                                break
                            elif q_result == "auth_error":
                                log_debug(f"AUTH_ERROR [{state.short}] vid={vid} flow=questionnaire")
                                state.cookies_expired = True
                                state.paused = True
                                self._add_log(
                                    state.short, state.color,
                                    "⚠️ Куки протухли! Обновите куки и снимите паузу.", "error",
                                )
                                self._add_acc_event(state, "⚠️", "error", "Авторизация", "", "Обновите куки")
                                break
                            else:
                                # Не удалось — считаем неудачи
                                state._test_failures[vid] = state._test_failures.get(vid, 0) + 1
                                if state._test_failures[vid] >= 2:
                                    # Permanently mark as failed test after 2 attempts
                                    add_test_vacancy(vid, title, company,
                                                     acc["name"], acc.get("resume_hash", ""))
                                state.tests += 1
                                state.action_history.append(f"\U0001f9ea {display_title[:25]}")
                                self._add_response(state, vid, title, company, "test")
                                self._add_log(state.short, state.color,
                                              f"\U0001f9ea Тест (не пройден, попытка {state._test_failures[vid]}): {display_title}", "warning")
                                self._add_acc_event(state, "\U0001f9ea", "test",
                                                    title or vid, company, "не пройден")

                    elif result == "already":
                        state.already_applied += 1
                        already_info = state.vacancy_meta.get(vid, {})
                        add_applied(acc["name"], vid, already_info if already_info else None)
                        state.action_history.append(f"\U0001f504 {vid}")
                        self._add_response(state, vid, "", "", "already")

                    elif result == "limit":
                        log_debug(f"HH_LIMIT [{state.short}] vid={vid} retry_after={info.get('retry_after_seconds', '?')}")
                        state.limit_exceeded = True
                        if CONFIG.stop_on_hh_limit:
                            # Hard stop — no retries
                            state.hard_stopped = True
                            state.paused = True
                            state.status = "limit"
                            state.status_detail = "\U0001f6d1 Лимит HH — остановлен до завтра"
                            self._add_log(
                                state.short, state.color,
                                f"\U0001f6d1 ЛИМИТ HH! Бот остановлен. Сбросится в 00:00 МСК. Снимите паузу вручную.",
                                "error",
                            )
                        else:
                            state.limit_reset_time = datetime.now() + timedelta(
                                minutes=CONFIG.limit_check_interval
                            )
                            state.status = "limit"
                            state.status_detail = f"Проверка в {state.limit_reset_time.strftime('%H:%M')}"
                            self._add_log(
                                state.short, state.color,
                                f"\U0001f6ab ЛИМИТ! Повторная попытка в {state.limit_reset_time.strftime('%H:%M')}",
                                "error",
                            )
                        break

                    elif result == "auth_error":
                        if state.use_oauth or CONFIG.use_oauth_apply:
                            # OAuth mode — web cookies expired but OAuth handles apply
                            # Log once per cycle, don't count as error (OAuth is working)
                            if not getattr(state, '_web_auth_warned', False):
                                self._add_log(
                                    state.short, state.color,
                                    "⚠️ Web cookies истекли (OAuth откликов продолжает работать)", "warning",
                                )
                                state._web_auth_warned = True
                            log_debug(f"AUTH_ERROR [{state.short}] vid={vid} flow=apply")
                            state.cookies_expired = True
                        else:
                            log_debug(f"AUTH_ERROR [{state.short}] vid={vid} flow=apply")
                            state.cookies_expired = True
                            state.paused = True
                            self._add_log(
                                state.short, state.color,
                                "⚠️ Куки протухли! Обновите куки и снимите паузу.", "error",
                            )
                            self._add_acc_event(state, "⚠️", "error", "Авторизация", "", "Обновите куки")
                            break

                    elif result == "error":
                        state.errors += 1
                        state.consecutive_errors += 1
                        state.action_history.append(f"❌ {vid}")
                        self._add_response(state, vid, "", "", "error")
                        raw = info.get("raw", "")[:80] if info else ""
                        exc = info.get("exception", "") if info else ""
                        debug_info = raw or exc or "unknown"
                        self._add_log(state.short, state.color, f"❌ {vid}: {debug_info}", "error")
                        self._add_acc_event(state, "❌", "error", vid, "", debug_info[:60])
                        self._check_auto_pause(state)

                if state.limit_exceeded:
                    break

                i += batch_size
                if i < len(filtered):
                    time.sleep(CONFIG.response_delay)

            # Очистка
            state.current_vacancy_title = ""
            state.current_vacancy_company = ""
            if state.short in self.vacancy_queues:
                self.vacancy_queues[state.short] = {
                    "vacancies": [],
                    "current": 0,
                    "color": state.color,
                }

            if not state.limit_exceeded:
                state.status = "waiting"
                state.status_detail = "Цикл завершён"
                self._add_log(
                    state.short, state.color,
                    f"⏳ Цикл завершён, пауза {CONFIG.pause_between_cycles}с",
                    "info",
                )
                if self._stop_event.wait(CONFIG.pause_between_cycles):
                    return

    async def _collect_all_urls_parallel(self, state: AccountState) -> tuple:
        """
        Параллельный сбор вакансий со ВСЕХ URL и страниц одновременно.
        Возвращает (results_by_url: dict[url, set[ids]], salary_map: dict[vid, int|None], schedule_map: dict[vid, set])
        """
        acc = state.acc
        xsrf = acc.get("cookies", {}).get("_xsrf", "")
        if not xsrf:
            return {}, {}, {}
        headers = get_headers(xsrf)
        sem = asyncio.Semaphore(CONFIG.max_concurrent * 3)

        # enable_cleanup_closed=True — закрывает половинно-закрытые TCP keep-alive
        # подключения (HH иногда дропает их), иначе fetch падает с ServerDisconnectedError.
        connector = aiohttp.TCPConnector(
            limit=CONFIG.max_concurrent * 3,
            enable_cleanup_closed=True,
        )

        all_tasks = []
        url_pages = _url_pages_map()
        acc_url_pages = acc.get("url_pages", {})  # per-account override
        effective_urls = acc.get("urls") or [_url_entry(u)["url"] for u in CONFIG.url_pool]
        # Build extra search filter params from config
        # Note: HH only accepts ONE label param; low_competition takes priority
        extra_params = ""
        if CONFIG.filter_low_competition:
            extra_params += "&label=low_performance"
        elif CONFIG.filter_agencies:
            extra_params += "&label=not_from_agency"
        if CONFIG.search_period_days > 0:
            extra_params += f"&search_period={CONFIG.search_period_days}"
        for url_idx, url in enumerate(effective_urls):
            pages = acc_url_pages.get(url) or url_pages.get(url, CONFIG.pages_per_url)
            sep = "&" if "?" in url else "?"
            for page in range(pages):
                page_url = f"{url}{sep}page={page}{extra_params}"
                all_tasks.append((url_idx, url, page, page_url))

        total_tasks = len(all_tasks)
        results_by_url = {url: [] for url in effective_urls}
        salary_map = {}
        completed = 0

        # connector передаётся явно — ClientSession его НЕ закрывает,
        # нужен ручной close, иначе утечка socket'ов на каждый цикл (swarm-11 #1).
        async with aiohttp.ClientSession(
            headers=headers, cookies=acc["cookies"], connector=connector,
            connector_owner=True,  # делегируем close обратно сессии
        ) as session:
            async def fetch_one(url_idx, url, page, page_url):
                nonlocal completed
                if state._deleted:
                    return url, set(), {}, {}, {}
                html = await fetch_page(session, page_url, sem)
                completed += 1
                state.status_detail = f"Загрузка {completed}/{total_tasks}"
                if html and _is_login_page(html):
                    if not (state.use_oauth or CONFIG.use_oauth_apply):
                        log_debug(f"AUTH_ERROR [{state.short}] vid=- flow=collect")
                        state.cookies_expired = True
                    return url, set(), {}, {}, {}
                if html:
                    ids = parse_ids(html)
                    salaries = parse_salaries(html, ids)
                    meta = parse_vacancy_meta(html)
                    schedules = parse_work_schedules(html, ids)
                    return url, ids, salaries, meta, schedules
                return url, set(), {}, {}, {}

            tasks = [
                fetch_one(url_idx, url, page, page_url)
                for url_idx, url, page, page_url in all_tasks
            ]
            task_results = await asyncio.gather(*tasks, return_exceptions=True)

            schedule_map = {}
            for result in task_results:
                if isinstance(result, Exception):
                    log_debug(f"❌ Ошибка при загрузке: {result}")
                    continue
                url, ids, salaries, meta, schedules = result
                results_by_url[url].extend(ids)
                salary_map.update(salaries)
                state.vacancy_meta.update(meta)
                for vid, sched_set in schedules.items():
                    if sched_set:
                        schedule_map.setdefault(vid, set()).update(sched_set)

        return {url: set(ids) for url, ids in results_by_url.items()}, salary_map, schedule_map

    def _process_llm_replies(self, state: AccountState) -> None:
        """Check recent unread negotiations for employer messages and auto-reply using LLM."""
        if not state.llm_enabled:
            return
        # Non-blocking: if another thread is already processing this account, skip
        if not state._llm_lock.acquire(blocking=False):
            log_debug(f"LLM [{state.short}]: уже выполняется, пропуск")
            return
        try:
            self._process_llm_replies_inner(state)
        finally:
            state._llm_lock.release()

    def _process_llm_replies_inner(self, state: AccountState) -> None:
        """Inner implementation — called only when _llm_lock is held."""
        replied = 0

        # Sync _llm_no_chat from persisted DB (catches 409 failures from previous sessions)
        state._llm_no_chat.update(get_no_chat_neg_ids())
        # Seed llm_replied_msgs from persisted store ONCE per worker lifetime —
        # повторный merge каждый цикл с обрезкой делал бы trim случайным (set без порядка)
        # и мог выкидывать только что записанные ключи.
        if not getattr(state, "_replied_seeded", False):
            # dict-init: ключи seeded из disk — для них insertion-order не важен (legacy).
            for _k in get_replied_keys():
                state.llm_replied_msgs[_k] = None
            state._replied_seeded = True

        # Memory leak prevention: purge expired temp_skip + cap in-memory sets.
        now_ts = time.time()
        state._llm_temp_skip = {
            k: v for k, v in state._llm_temp_skip.items() if v > now_ts
        }
        if len(state.llm_replied_msgs) > 5000:
            # Hard cap — dict сохраняет insertion order, [-2000:] retains *recent* keys
            # (раньше set делал случайный slice, mid-session re-reply, kimi-r14-2 #11).
            recent = list(state.llm_replied_msgs)[-2000:]
            state.llm_replied_msgs = dict.fromkeys(recent)
        with self._llm_sent_lock:
            if len(self._llm_sent_global) > 10000:
                self._llm_sent_global = set(list(self._llm_sent_global)[-5000:])
                # перестраиваем индекс после массовой обрезки
                self._llm_sent_by_neg_id = {}
                for gk in self._llm_sent_global:
                    self._llm_sent_by_neg_id.setdefault(gk[1], set()).add(gk)

        # Fetch recent chat pages sorted by last activity. Chats needing reply
        # (employer just wrote) will always be near the top.
        self._add_log(state.short, state.color, "\U0001f916 LLM: загружаю список чатов…", "info")
        log_debug(f"LLM [{state.short}]: загружаю чат-лист")
        items_by_id, display_info, cur_pid = _fetch_chat_list(state.acc, max_pages=3)
        log_debug(f"LLM [{state.short}]: чат-лист загружен, {len(items_by_id)} чатов")

        # Process items that need a reply: NEGOTIATION type, unread, from employer, not rejection
        candidates = []
        skipped_ours = 0
        skipped_system = 0
        skipped_read = 0
        skipped_locked = 0
        for item_id, item in items_by_id.items():
            if item.get("type") != "NEGOTIATION":
                continue
            unread = item.get("unreadCount", 0)
            last_msg = item.get("lastMessage") or {}
            sender_id = last_msg.get("participantId", "")
            last_text = (last_msg.get("text") or "")[:40]
            wf = last_msg.get("workflowTransition") or {}
            from_employer = bool(sender_id and cur_pid and sender_id != cur_pid)
            # Early check: known 409 (persisted from DB or current session)
            if item_id in state._llm_no_chat:
                skipped_locked += 1
                log_debug(f"LLM [{state.short}] {item_id}: 409-закрыт, пропуск кандидата")
                continue
            # Early check: HH пометил как DISCARD — нет смысла отвечать, экономим LLM API call.
            if item_id in state.hh_discard_neg_ids:
                skipped_locked += 1
                # Также добавляем в постоянный _llm_no_chat чтобы не проверять каждый цикл.
                state._llm_no_chat.add(item_id)
                log_debug(f"LLM [{state.short}] {item_id}: HH-DISCARD, пропуск кандидата")
                continue
            # Early check: chat locked via text/flags (employer disabled messaging or invite-only)
            if _check_chat_locked(item):
                skipped_locked += 1
                log_debug(f"LLM [{state.short}] {item_id}: чат заблокирован, пропуск кандидата len={len(last_text)}")
                continue
            # Early check: writePossibility from chatik API
            write_poss = (item.get("writePossibility") or {}).get("name", "")
            if write_poss not in ("ENABLED_FOR_ALL", "ENABLED_FOR_ALL_BY_EMPLOYER", ""):
                skipped_locked += 1
                log_debug(f"LLM [{state.short}] {item_id}: writePossibility={write_poss}, пропуск")
                continue
            if unread == 0:
                if from_employer and not wf:
                    last_msg_id_early = str((item.get("lastMessage") or {}).get("id", ""))
                    key_early = (str(item_id), last_msg_id_early)
                    if key_early not in state.llm_replied_msgs:
                        log_debug(f"LLM [{state.short}] {item_id}: unread=0 но от работодателя, не отвечали — добавляю кандидатом: len={len(last_text)}")
                    else:
                        skipped_read += 1
                        di = display_info.get(str(item_id), {})
                        upsert_interview(str(item_id), acc=state.short, acc_color=state.color,
                                         employer=di.get("subtitle", ""), vacancy_title=di.get("title", ""),
                                         chat_status="waiting_hr")
                        log_debug(f"LLM [{state.short}] {item_id}: unread=0, от работодателя, уже отвечали, пропуск: len={len(last_text)}")
                        continue
                else:
                    skipped_read += 1
                    continue
            if cur_pid and sender_id == cur_pid:
                skipped_ours += 1
                log_debug(f"LLM [{state.short}] {item_id}: unread={unread}, последнее наше, пропуск")
                di = display_info.get(str(item_id), {})
                upsert_interview(str(item_id), acc=state.short, acc_color=state.color,
                                 employer=di.get("subtitle", ""), vacancy_title=di.get("title", ""),
                                 chat_status="waiting_hr")
                continue
            if wf:
                wf_id = wf.get("id", "") if isinstance(wf, dict) else ""
                if isinstance(wf_id, str) and wf_id:
                    skipped_system += 1
                    log_debug(f"LLM [{state.short}] {item_id}: unread={unread}, системное событие wf={wf_id!r}, пропуск")
                    continue
                log_debug(f"LLM [{state.short}] {item_id}: unread={unread}, wf.id={wf_id!r} (числовой, реальное сообщение)")
            # Не флудим логи структурой каждого item — только метаданные кандидата (swarm-16 #8).
            log_debug(f"LLM [{state.short}] {item_id}: ✅ кандидат unread={unread}, sender={sender_id}, len={len(last_text)}")
            candidates.append(item_id)

        log_debug(f"LLM [{state.short}]: {len(candidates)} кандидатов (прочитанных: {skipped_read}, наших: {skipped_ours}, системных: {skipped_system})")
        if not candidates:
            state.llm_pending_chats = 0
            state.llm_status = f"\U0001f4a4 Нет новых (наших: {skipped_ours}, закр.: {skipped_locked})"
            self._add_log(state.short, state.color,
                f"\U0001f916 LLM: нет новых сообщений (прочит.: {skipped_read}, наших: {skipped_ours}, сист.: {skipped_system}, закрыт: {skipped_locked})", "info")
            return

        state.llm_pending_chats = len(candidates)
        state.llm_status = f"\U0001f504 Обработка {len(candidates)} чатов..."
        self._add_log(state.short, state.color, f"\U0001f916 LLM: {len(candidates)} чатов требуют ответа", "info")

        for i, neg_id in enumerate(candidates[:15]):  # limit to 15 per cycle
            if not state.llm_enabled or not CONFIG.llm_enabled:
                self._add_log(state.short, state.color, f"\U0001f916 LLM: выключен в процессе цикла, прерываю", "warning")
                break
            # Reset per-iteration: иначе exception на новой итерации видит global_key из ПРЕДЫДУЩЕЙ.
            global_key = None
            try:
                if neg_id in state._llm_no_chat:
                    item = items_by_id.get(neg_id, {})
                    info = display_info.get(str(neg_id), {})
                    emp = (info.get("subtitle") or neg_id).strip(" ,")[:25]
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{emp}] \U0001f512 переписка закрыта, пропуск", "warning", neg_id=neg_id)
                    continue

                item = items_by_id.get(neg_id)
                if not item:
                    log_debug(f"LLM [{state.short}] {neg_id}: не найден в items_by_id, пропуск")
                    continue
                thread = _build_thread_from_chat_item(item, display_info, cur_pid, neg_id)
                employer_short = thread.get("employer_name", neg_id)[:25]
                if thread.get("error"):
                    self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] ошибка треда: {thread['error']}", "error", neg_id=neg_id)
                    continue

                employer = thread.get("employer_name", neg_id)[:35]
                employer_msg = thread.get("last_employer_msg", "")
                vacancy_title = thread.get("vacancy_title", "")

                if not thread.get("needs_reply") and not thread.get("chat_locked"):
                    raw_item = items_by_id.get(neg_id, {})
                    raw_unread = raw_item.get("unreadCount", 0)
                    raw_last = raw_item.get("lastMessage") or {}
                    raw_sender = raw_last.get("participantId", "")
                    if raw_unread == 0 and cur_pid and raw_sender and raw_sender != cur_pid:
                        thread["needs_reply"] = True
                        if not employer_msg:
                            employer_msg = (raw_last.get("text") or "").strip()
                            thread["last_employer_msg"] = employer_msg

                if thread.get("chat_locked"):
                    lock_reason = thread["chat_locked"]
                    log_debug(f"LLM [{state.short}] {neg_id}: переписка недоступна — {lock_reason!r}")
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] \U0001f512 переписка недоступна, пропуск", "warning", neg_id=neg_id)
                    state.llm_replied_msgs[(neg_id, "locked")] = None
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color, chat_status="locked")
                    continue

                upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                 employer=employer, vacancy_title=vacancy_title,
                                 employer_last_msg=employer_msg if employer_msg else None,
                                 needs_reply=bool(thread.get("needs_reply")))

                if not thread.get("needs_reply"):
                    log_debug(f"LLM [{state.short}] {neg_id}: ответ не нужен (последнее сообщение — от соискателя)")
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color, chat_status="waiting_hr")
                    self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] последнее сообщение наше, пропуск", "info", neg_id=neg_id)
                    continue
                last_msg_id = thread["last_msg_id"]
                key = (neg_id, last_msg_id)
                # Legacy: pre-r1 records без replied_msg_id мечены sentinel '__legacy__'.
                # Если такой sentinel есть — значит мы уже отвечали в этот чат до апгрейда.
                # Пропускаем, не дожидаясь нового HH-сообщения (r13-1 #6).
                if key in state.llm_replied_msgs or (neg_id, "__legacy__") in state.llm_replied_msgs:
                    log_debug(f"LLM [{state.short}] {neg_id}: уже отвечали на msg {last_msg_id}")
                    self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] уже отвечали в этой сессии, пропуск", "info", neg_id=neg_id)
                    continue
                # temp_skip может быть выставлен и под key=(neg_id, last_msg_id), и под
                # (neg_id, "exception") (chat-level backoff после исключения в H6).
                _skip_until = max(
                    state._llm_temp_skip.get(key, 0),
                    state._llm_temp_skip.get((neg_id, "exception"), 0),
                )
                if time.time() < _skip_until:
                    mins = max(1, int((_skip_until - time.time()) / 60))
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] повтор через ~{mins}м (ошибка в предыдущем цикле)", "info", neg_id=neg_id)
                    log_debug(f"LLM [{state.short}] {neg_id}: temp_skip до {_skip_until:.0f}")
                    continue
                global_key = (cur_pid, neg_id, last_msg_id)
                with self._llm_sent_lock:
                    if global_key in self._llm_sent_global:
                        log_debug(f"LLM [{state.short}] {neg_id}: уже отправлено другим аккаунтом (pid={cur_pid})")
                        self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] уже отправлено другим аккаунтом, пропуск", "info")
                        state.llm_replied_msgs[key] = None
                        continue

                progress = f"[{i+1}/{min(len(candidates),15)}]"
                self._add_log(state.short, state.color,
                    f"\U0001f916 {progress} [{employer_short}]: «{employer_msg[:50]}»", "info", neg_id=neg_id)
                log_debug(f"LLM [{state.short}] {progress} {neg_id} ({employer_short}): загружаю историю чата")
                cover_letter = state.acc.get("letter", "") if CONFIG.llm_use_cover_letter else ""
                # Fetch resume for LLM context
                if CONFIG.llm_use_resume:
                    rh = state.acc.get("resume_hash", "")
                    _cached = rh and rh in _resume_cache and (time.time() - _resume_cache[rh][1] < _RESUME_CACHE_TTL)
                    resume_text = fetch_resume_text(state.acc)
                    if resume_text:
                        src = "кэш" if _cached else "загружено"
                        self._add_log(state.short, state.color,
                            f"\U0001f916 \U0001f4c4 Резюме в контексте LLM ({src}, {len(resume_text)} симв.)", "info", neg_id=neg_id)
                    else:
                        self._add_log(state.short, state.color,
                            f"\U0001f916 \U0001f4c4 Резюме не удалось загрузить — LLM работает без него", "warning", neg_id=neg_id)
                else:
                    resume_text = ""
                full_history = _fetch_chat_history(state.acc, neg_id, max_messages=20)
                conversation = full_history if full_history else thread["messages"]

                _last_emp_raw = None
                if full_history:
                    for msg_raw in reversed(full_history):
                        if msg_raw.get("sender") == "employer":
                            _last_emp_raw = msg_raw
                            break
                _raw_actions = (_last_emp_raw or {}).get("actions") or {}
                _text_buttons = _raw_actions.get("text_buttons", [])
                _is_bot_msg = (_last_emp_raw or {}).get("is_bot", False)
                if _text_buttons:
                    # Умный выбор кнопки: heuristic для очевидных Да/Нет,
                    # LLM-консультация если кнопок 3+ или Да/Нет не определяется.
                    from app.llm import pick_robot_button as _pick_robot_button
                    _btn_idx, btn_text, _btn_source = _pick_robot_button(
                        _text_buttons, conversation, thread.get("employer_name", ""), state.short,
                    )
                    if not btn_text:
                        btn_text = (_text_buttons[0].get("text") if _text_buttons else "ДА") or "ДА"
                    log_debug(
                        f"LLM [{state.short}] {neg_id}: робот-рекрутер, кнопки={[b.get('text') for b in _text_buttons]}, "
                        f"выбрана [{_btn_idx}] '{btn_text}' (src={_btn_source})"
                    )
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] \U0001f916 Робот → '{btn_text}' ({_btn_source})", "info", neg_id=neg_id)
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                     employer=employer_short, vacancy_title=vacancy_title,
                                     chat_status="robot")
                    ok = send_negotiation_message(state.acc, neg_id, btn_text)
                    if ok and ok != "chat_not_found":
                        state.llm_replied_msgs[key] = None
                        replied += 1
                        ts = datetime.now().strftime("%H:%M")
                        self.llm_log.appendleft({
                            "time": ts, "acc": state.short, "color": state.color,
                            "employer": employer_short, "vacancy_title": vacancy_title,
                            "neg_id": neg_id, "employer_msg": employer_msg[:50],
                            "bot_reply": f"\U0001f916 Кнопка: {btn_text}", "sent": True,
                        })
                        self._persist_llm_log({
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "acc": state.short,
                            "neg_id": str(neg_id),
                            "last_msg_id": str(last_msg_id),
                            "employer": employer_short,
                            "reply_len": len(btn_text),
                            "send_ok": True,
                            "source": "robot",
                        })
                    elif ok == "chat_not_found":
                        state._llm_no_chat.add(neg_id)
                        state.llm_replied_msgs[key] = None
                        log_debug(f"LLM [{state.short}] {neg_id}: робот-кнопка 409, чат закрыт — добавлен в _llm_no_chat")
                    elif not ok:
                        state._llm_temp_skip[key] = time.time() + 1800
                    continue

                has_employer_msg = any(m.get("sender") == "employer" for m in conversation)
                last_real_sender = conversation[-1].get("sender") if conversation else None
                if not has_employer_msg:
                    log_debug(f"LLM [{state.short}] {neg_id}: нет реальных сообщений работодателя (только системные), пропуск")
                    state.llm_replied_msgs[key] = None
                    continue
                if last_real_sender == "applicant":
                    log_debug(f"LLM [{state.short}] {neg_id}: последнее реальное сообщение наше — уже ответили, пропуск")
                    state.llm_replied_msgs[key] = None
                    continue
                _consecutive_ours = 0
                for _cm in reversed(conversation):
                    if _cm.get("sender") == "applicant":
                        _consecutive_ours += 1
                    else:
                        break
                state._msg_consecutive[neg_id] = _consecutive_ours
                if _consecutive_ours >= 4:
                    log_debug(f"LLM [{state.short}] {neg_id}: in_a_row_limit: {_consecutive_ours} сообщений без ответа HR, пропуск")
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] ⚠️ in_a_row_limit: {_consecutive_ours} сообщения без ответа HR, пропуск", "warning", neg_id=neg_id)
                    state.llm_replied_msgs[key] = None
                    continue
                # Если для этого (neg_id, last_msg_id) уже есть кэшированный черновик
                # с прошлого цикла (auto_send был выкл) — используем его, чтобы не жечь
                # токены заново. Если auto_send всё ещё False — вообще скипаем без
                # перегенерации (черновик уже сохранён в llm_log и interviews DB).
                cached_draft = state._llm_drafts.get(key)
                if cached_draft and not CONFIG.llm_auto_send:
                    log_debug(f"LLM [{state.short}] {neg_id}: уже есть черновик в кэше, auto_send выкл — пропуск")
                    continue
                if cached_draft and CONFIG.llm_auto_send:
                    log_debug(f"LLM [{state.short}] {neg_id}: отправляю кэшированный черновик ({len(cached_draft)} симв.)")
                    reply_text = cached_draft
                else:
                    log_debug(f"LLM [{state.short}] {neg_id}: история {len(conversation)} сообщений, резюме {len(resume_text)} симв., отправляю в LLM")
                    self._add_log(state.short, state.color,
                        f"\U0001f916 {progress} [{employer_short}]: история {len(conversation)} сообщ., жду LLM…", "info", neg_id=neg_id)
                    reply_text = generate_llm_reply(conversation, thread.get("employer_name", ""), cover_letter, resume_text)
                    if not reply_text:
                        self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] LLM вернул пустой ответ, повтор через 30м", "warning", neg_id=neg_id)
                        log_debug(f"LLM [{state.short}] {neg_id}: пустой ответ от LLM, ставим temp_skip 30м")
                        state._llm_temp_skip[key] = time.time() + 1800
                        continue
                    log_debug(f"LLM [{state.short}] {neg_id}: ответ получен ({len(reply_text)} симв.), отправляю")

                ts = datetime.now().strftime("%d.%m %H:%M")

                if CONFIG.llm_auto_send:
                    with self._llm_sent_lock:
                        if global_key in self._llm_sent_global:
                            log_debug(f"LLM [{state.short}] {neg_id}: другой поток уже отправил (pid={cur_pid}), пропуск")
                            self._add_log(state.short, state.color, f"\U0001f916 [{employer_short}] другой аккаунт уже отправил, пропуск", "info")
                            state.llm_replied_msgs[key] = None
                            continue
                        self._llm_sent_global.add(global_key)
                        self._llm_sent_by_neg_id.setdefault(neg_id, set()).add(global_key)
                    self._add_log(state.short, state.color,
                        f"\U0001f916 [{employer_short}] отправляю: «{reply_text[:60]}»", "info", neg_id=neg_id)
                    log_debug(f"LLM [{state.short}] {neg_id}: отправляю сообщение в chatik")
                    ok = send_negotiation_message(state.acc, neg_id, reply_text, topic_id=thread.get("topic_id", ""))
                    if ok == "chat_not_found":
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                            self._llm_sent_by_neg_id.get(neg_id, set()).discard(global_key)
                        state.llm_replied_msgs[key] = None
                        state._llm_no_chat.add(neg_id)
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         employer=employer, vacancy_title=vacancy_title,
                                         chat_not_found=True)
                        self._add_log(state.short, state.color,
                            f"\U0001f916 [{employer_short}] \U0001f512 переписка закрыта (409), пропуск", "warning", neg_id=neg_id)
                        continue
                    if ok:
                        state.llm_replied_msgs[key] = None
                        state._llm_drafts.pop(key, None)  # отправили — кэш не нужен
                        state._msg_consecutive[neg_id] = state._msg_consecutive.get(neg_id, 0) + 1
                        state._llm_neg_failures.pop(neg_id, None)  # clear backoff on success
                        replied += 1
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         llm_reply=reply_text, llm_sent=True,
                                         replied_msg_id=last_msg_id)
                        self._add_log(state.short, state.color,
                            f"\U0001f916 Авто-ответ → {employer}: {reply_text[:60]}…", "success", neg_id=neg_id)
                        self.llm_log.appendleft({
                            "time": ts, "acc": state.short, "color": state.color,
                            "employer": employer, "vacancy_title": vacancy_title,
                            "neg_id": neg_id, "employer_msg": employer_msg,
                            "bot_reply": reply_text, "sent": True,
                        })
                        self._persist_llm_log({
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "acc": state.short,
                            "neg_id": str(neg_id),
                            "last_msg_id": str(last_msg_id),
                            "employer": employer,
                            "reply_len": len(reply_text),
                            "send_ok": True,
                            "source": "auto_send",
                        })
                    else:
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                            self._llm_sent_by_neg_id.get(neg_id, set()).discard(global_key)
                        state._llm_temp_skip[key] = time.time() + 1800
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         llm_reply=reply_text, llm_sent=False)
                        self._add_log(state.short, state.color,
                            f"\U0001f916 Черновик (ошибка отправки, повтор ~30м) → {employer}: {reply_text[:60]}…", "warning", neg_id=neg_id)
                        self.llm_log.appendleft({
                            "time": ts, "acc": state.short, "color": state.color,
                            "employer": employer, "vacancy_title": vacancy_title,
                            "neg_id": neg_id, "employer_msg": employer_msg,
                            "bot_reply": reply_text, "sent": False,
                        })
                        self._persist_llm_log({
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "acc": state.short,
                            "neg_id": str(neg_id),
                            "last_msg_id": str(last_msg_id),
                            "employer": employer,
                            "reply_len": len(reply_text),
                            "send_ok": False,
                            "source": "draft_error",
                        })
                else:
                    # auto_send=False — сохраняем черновик в кэш чтобы при включении
                    # auto_send отправить без повторного LLM-вызова.
                    state._llm_drafts[key] = reply_text
                    # НЕ помечаем llm_replied_msgs[key]=None — иначе при флипе auto_send
                    # бот посчитает чат «уже обработан» и пропустит. Без этой метки
                    # следующий цикл увидит чат, найдёт черновик в кэше и (если
                    # auto_send=True) отправит.
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                     llm_reply=reply_text, llm_sent=False)
                    self._add_log(state.short, state.color,
                        f"\U0001f916 Черновик [{employer}] (вкл «Автоотправку» → отправлю): {reply_text[:60]}…", "info", neg_id=neg_id)
                    self.llm_log.appendleft({
                        "time": ts, "acc": state.short, "color": state.color,
                        "employer": employer, "vacancy_title": vacancy_title,
                        "neg_id": neg_id, "employer_msg": employer_msg,
                        "bot_reply": reply_text, "sent": False,
                    })
                    self._persist_llm_log({
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "acc": state.short,
                        "neg_id": str(neg_id),
                        "last_msg_id": str(last_msg_id),
                        "employer": employer,
                        "reply_len": len(reply_text),
                        "send_ok": False,
                        "source": "draft_manual",
                    })

                time.sleep(3)  # rate limit between messages
            except Exception as e:
                log_exception(f"_process_llm_replies {neg_id}", e)
                try:
                    # Чистим только текущий global_key. На иммедиатных exception'ах
                    # (до reserve блока) он = None — ничего не трогаем.
                    if global_key is not None:
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                            bucket = self._llm_sent_by_neg_id.get(neg_id)
                            if bucket is not None:
                                bucket.discard(global_key)
                                if not bucket:
                                    self._llm_sent_by_neg_id.pop(neg_id, None)
                except Exception:
                    pass
                # Backoff at chat-level: предотвращает бесконечный retry перманентной ошибки.
                # 1 ошибка → 5 мин, 2 → 15 мин, 3-5 → 1 час, после 5 → 24 часа (но не permanent —
                # _llm_no_chat зарезервирован под реальный 409, чтобы не путать).
                fail_count = state._llm_neg_failures.get(neg_id, 0) + 1
                state._llm_neg_failures[neg_id] = fail_count
                backoff = {1: 300, 2: 900, 3: 3600, 4: 3600, 5: 3600}.get(fail_count, 86400)
                state._llm_temp_skip[(neg_id, "exception")] = time.time() + backoff

        state.llm_replied_count += replied
        if replied:
            state.llm_status = f"✅ {replied} ответов отправлено"
            log_debug(f"LLM auto-reply [{state.short}]: {replied} ответов отправлено")
        elif candidates:
            state.llm_status = f"⏳ {len(candidates)} чатов, 0 отправлено"

    def _fetch_hh_stats_worker(self, idx: int, state: AccountState) -> None:
        """Thread worker for HH stats polling — auto-restarts on crash.

        Без этого цикла один краш парсинга / network exception → у аккаунта
        НАВСЕГДА выключаются stats + LLM до перезапуска процесса (swarm-1 critical).
        """
        while not self._stop_event.is_set() and not getattr(state, "_deleted", False):
            try:
                self._fetch_hh_stats_worker_inner(idx, state)
                return  # inner вышел нормально (stop_event / _deleted) — выходим из restart-loop
            except Exception as e:
                log_exception(f"STATS WORKER CRASHED [{state.short}]", e)
                self._add_log(
                    state.short, state.color,
                    f"⚠️ Stats worker упал: {str(e)[:80]} — рестарт через 30с",
                    "error",
                )
                # Используем wait вместо sleep, чтобы shutdown будил быстро.
                if self._stop_event.wait(30):
                    return

    def _fetch_hh_stats_worker_inner(self, idx: int, state: AccountState) -> None:
        while not self._stop_event.is_set():
            # state.paused тоже учитываем — иначе paused account продолжает hammer HH APIs (swarm-12 #7).
            while (
                (self.paused or state.paused or getattr(state, "hard_stopped", False))
                and not self._stop_event.is_set()
                and not getattr(state, "_deleted", False)
            ):
                if self._stop_event.wait(2):
                    return
            if self._stop_event.is_set() or getattr(state, '_deleted', False):
                break

            state.hh_stats_loading = True
            try:
                stats = fetch_hh_negotiations_stats(state.acc)
                if stats.get("auth_error"):
                    log_debug(f"AUTH_ERROR [{state.short}] vid=- flow=stats")
                    state.cookies_expired = True
                    self._add_log(
                        state.short, state.color,
                        "⚠️ Куки протухли! (HH stats) Обновите куки.", "error",
                    )
                    state.hh_stats_loading = False
                    self._stop_event.wait(max(CONFIG.llm_check_interval * 60, 120))
                    continue
                old_interviews = state.hh_interviews
                state.hh_interviews = stats["interview"]
                state.hh_interviews_recent = stats["recent_interview"]
                state.hh_viewed = stats["viewed"]
                state.hh_not_viewed = stats["not_viewed"]
                state.hh_discards = stats["discard"]
                state.hh_interviews_list = stats["interviews_list"]
                state.hh_interview_neg_ids = stats.get("neg_ids", [])
                state.hh_discard_neg_ids = set(str(x) for x in stats.get("discard_neg_ids", []))
                state.hh_unread_by_employer = stats.get("unread_by_employer", 0)

                for neg_id in state.hh_interview_neg_ids:
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color)
                if len(state.hh_interview_neg_ids) == len(stats["interviews_list"]):
                    for neg_id, item in zip(state.hh_interview_neg_ids, stats["interviews_list"]):
                        parts = item.get("text", "").rsplit(" ", 1)
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         vacancy_title=item.get("text", ""))

                offers = fetch_hh_possible_offers(state.acc)
                state.hh_possible_offers = offers

                rs = fetch_resume_stats(state.acc)
                state.resume_views_7d = rs["views"]
                state.resume_views_new = rs["views_new"]
                state.resume_shows_7d = rs["shows"]
                state.resume_invitations_7d = rs["invitations"]
                state.resume_invitations_new = rs["invitations_new"]
                state.resume_next_touch_seconds = rs["next_touch_seconds"]
                state.resume_free_touches = rs["free_touches"]
                state.resume_global_invitations = rs["global_invitations"]
                state.resume_new_invitations_total = rs["new_invitations_total"]

                state.resume_view_history = fetch_resume_view_history(state.acc, limit=100)

                state.hh_stats_updated = datetime.now()

                if old_interviews > 0 and stats["interview"] > old_interviews:
                    new_count = stats["interview"] - old_interviews
                    self._add_log(
                        state.short, state.color,
                        f"\U0001f3af НОВОЕ ПРИГЛАШЕНИЕ! (+{new_count} интервью)",
                        "success",
                    )

                log_debug(
                    f"HH stats {state.short}: {stats['interview']} интервью, "
                    f"{rs['views']} просмотров резюме, {rs['new_invitations_total']} новых инвайтов"
                )

                if self.paused or state.paused:
                    log_debug(f"LLM [{state.short}]: пропуск — на паузе")
                    state.hh_stats_loading = False
                    if self._stop_event.wait(max(CONFIG.llm_check_interval * 60, 120)):
                        return
                    continue

                _has_llm = CONFIG.llm_api_key or any(
                    p.get("api_key") for p in (CONFIG.llm_profiles or []) if p.get("enabled", True)
                )
                _neg_count = len(state.hh_interview_neg_ids)
                if not CONFIG.llm_enabled:
                    log_debug(f"LLM [{state.short}]: пропуск — глобально выключено")
                elif not _has_llm:
                    self._add_log(state.short, state.color, "\U0001f916 LLM: нет API ключа ни в одном профиле", "warning")
                elif not state.llm_enabled:
                    log_debug(f"LLM [{state.short}]: пропуск — выключено для аккаунта")
                else:
                    if _neg_count:
                        self._add_log(state.short, state.color, f"\U0001f916 LLM: проверяю {_neg_count} переговоров…", "info")
                    else:
                        self._add_log(state.short, state.color, "\U0001f916 LLM: нет переговоров в статусе Интервью, проверяю чаты…", "info")
                    self._process_llm_replies(state)
            except Exception as e:
                log_exception(f"HH stats fetch error ({state.short})", e)
            finally:
                state.hh_stats_loading = False

            if self._stop_event.wait(max(CONFIG.llm_check_interval * 60, 120)):
                return
