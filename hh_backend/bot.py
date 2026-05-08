"""Runtime bot state, websocket manager, and background workers."""

import asyncio
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from fastapi import WebSocket

from .hh_client import *
from .state import CONFIG, accounts_data
from .storage import *

class AccountState:
    """Полное состояние аккаунта"""

    def __init__(self, acc_data: dict):
        self.acc = acc_data
        self.name = acc_data["name"]
        self.short = acc_data["short"]
        self.color = acc_data["color"]

        self.status = "idle"
        self.status_detail = ""

        self.sent = 0
        self.tests = 0
        self.errors = 0
        self.already_applied = 0
        self.found_vacancies = 0

        self.current_phase = ""
        self.current_url = ""
        self.current_url_idx = 0
        self.total_urls = len(acc_data["urls"])
        self.current_page = 0
        self.total_pages = CONFIG.pages_per_url

        self.current_vacancy_id = ""
        self.current_vacancy_title = ""
        self.current_vacancy_company = ""
        self.current_vacancy_idx = 0
        self.total_vacancies = 0

        self.vacancies_by_url = {}
        self.vacancies_queue = []

        self.limit_exceeded = False
        self.limit_reset_time = None

        self.resume_touch_enabled = True
        self.last_resume_touch = None
        self.next_resume_touch = None
        self.resume_touch_status = ""

        self.last_action_time = None
        self.cycle_start_time = None
        self.wait_until = None

        self.action_history = deque(maxlen=20)
        self.recent_responses = deque(maxlen=10)

        self.salary_skipped = 0       # Пропущено из-за зарплаты
        self.vacancy_salaries = {}    # {vid: salary_from_rub_or_None}
        self.vacancy_meta = {}        # {vid: {title, company}} из HTML поиска
        self.questionnaire_sent = 0   # Успешно пройдено опросов

        self.hh_interviews = 0
        self.hh_interviews_recent = 0  # за последние 60 дней
        self.hh_viewed = 0
        self.hh_not_viewed = 0
        self.hh_discards = 0
        self.hh_interviews_list = []
        self.hh_possible_offers = []
        self.hh_stats_updated = None
        self.hh_stats_loading = False

        # Статистика резюме
        self.resume_views_7d = 0
        self.resume_views_new = 0
        self.resume_shows_7d = 0
        self.resume_invitations_7d = 0
        self.resume_invitations_new = 0
        self.resume_next_touch_seconds = 0
        self.resume_free_touches = 0
        self.resume_global_invitations = 0
        self.resume_new_invitations_total = 0

        # История просмотров резюме
        self.resume_view_history: list = []   # [{employer_id, name, date, vacancy}]

        # Пауза на уровне аккаунта для web dashboard
        self.paused = False
        self._deleted = False  # Значение True останавливает рабочий поток

        # Журнал событий аккаунта: последние 8 событий показываются на карточке
        self.acc_event_log: deque = deque(maxlen=8)
        # Пропускать вакансии с обязательными тестами
        self.apply_tests: bool = bool(acc_data.get("apply_tests", False))
        # Счётчик подряд идущих ошибок для автопаузы
        self.consecutive_errors: int = 0
        # Количество вакансий по URL из последнего цикла сбора
        self.url_stats: dict = {}
        # Индивидуальная глубина страниц по URL для аккаунта: {url: pages}
        # Переопределяет глобальную глубину URL-пула для этого аккаунта
        # Хранится в acc["url_pages"]
        # Флаг истечения cookies: ставится при 401/403 или редиректе на логин
        self.cookies_expired: bool = False

        # Отслеживание LLM-автоответов
        self.llm_replied_msgs: set = set()   # {(neg_id, last_msg_id)} successfully replied (permanent per session)
        self._llm_temp_skip: dict = {}       # {(neg_id, last_msg_id): expiry_ts} — transient failure, retry after TTL
        self._llm_no_chat: set = set()       # {neg_id} chats that returned 409 (permanently closed/locked)
        self.hh_interview_neg_ids: list = [] # ID переговоров из последней загрузки INTERVIEW
        self.llm_enabled: bool = True        # Переключатель LLM для аккаунта; перекрывается глобальным CONFIG.llm_enabled
        self._llm_lock = threading.Lock()    # Защищает аккаунт от параллельных запусков _process_llm_replies


# ============================================================
# МЕНЕДЖЕР WEBSOCKET-ПОДКЛЮЧЕНИЙ
# ============================================================

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except TypeError as e:
                log_debug(f"broadcast serialize error (bug — check datetimes in snapshot): {e}")
                # Не роняем WebSocket при ошибках сериализации: исправляем данные
            except Exception as e:
                log_debug(f"broadcast ws error: {type(e).__name__}: {e}")
                dead.append(ws)
        for ws in dead:
            if ws in self.active:
                self.active.remove(ws)


# ============================================================
# МЕНЕДЖЕР БОТА
# ============================================================

class BotManager:
    def __init__(self):
        self.paused = False
        self._stop_event = threading.Event()
        self.account_states: list[AccountState] = []
        self.activity_log: deque = deque(maxlen=100)
        self.recent_responses: deque = deque(maxlen=20)
        self.llm_log: deque = deque(maxlen=200)    # История LLM-ответов
        self.vacancy_queues: dict = {}
        self._start_time: datetime = None
        self.temp_sessions: list = load_browser_sessions()  # сессии из браузера (персистентные)
        self.temp_states: dict[int, AccountState] = {}  # temp_idx -> AccountState для активных сессий
        # Глобальная дедупликация по всем аккаунтам: {(cur_pid, neg_id, last_msg_id)}
        # Предотвращает двойную отправку, если несколько аккаунтов используют одного HH-пользователя (один cur_pid)
        self._llm_sent_global: set = set()
        self._llm_sent_lock = threading.Lock()

    def _build_session_urls(self, resume_hash: str) -> list[str]:
        """URL поиска для браузерной сессии: resume-URL + keyword-URLs из глобального пула."""
#        resume_url = f"https://hh.ru/search/vacancy?resume={resume_hash}&order_by=publication_time&items_on_page=20"
        resume_url = f"https://hh.ru/search/vacancy?enable_snippets=true&ored_clusters=true&resume={resume_hash}&order_by=relevance&items_on_page=20"
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
            "urls": ts.get("urls") or self._build_session_urls(ts["resume_hash"]),
            "url_pages": ts.get("url_pages", {}),
        }
        state = AccountState(acc)
        self.temp_states[temp_idx] = state
        ts["bot_active"] = True
        save_browser_sessions(self.temp_sessions)
        t1 = threading.Thread(target=self._run_account_worker, args=(900 + temp_idx, state), daemon=True)
        t2 = threading.Thread(target=self._fetch_hh_stats_worker, args=(900 + temp_idx, state), daemon=True)
        t1.start()
        t2.start()
        self._add_log(state.short, "yellow", f"🌐 Сессия {ts['name']} запущена как бот", "success")
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
        for i, ts in enumerate(self.temp_sessions):
            if ts.get("bot_active") and ts.get("resume_hash"):
                self.activate_session(i)
        self._add_log("", "", "🚀 Бот запущен", "success")

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
        if state:
            state.paused = not state.paused
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
                f"🤖 LLM включён для {state.short}"
                if state.llm_enabled
                else f"🤖 LLM выключен для {state.short}"
            )
            self._add_log(state.short, state.color, msg, "info")

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
        self.activity_log.appendleft(entry)

    def _add_acc_event(self, state: AccountState, icon: str, etype: str,
                        title: str, company: str, extra: str = ""):
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
            state.paused = True
            self._add_log(
                state.short, state.color,
                f"⛔ Авто-пауза: {n} ошибок подряд. Снимите вручную.",
                "error",
            )

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
            "test": "🧪",
            "already": "🔄",
            "limit": "🚫",
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

            accounts.append({
                "idx": i,
                "name": s.name,
                "short": s.short,
                "color": s.color,
                "status": s.status,
                "status_detail": s.status_detail,
                "sent": s.sent,
                "total_applied": len((_cache_applied or {}).get(s.name, {})),
                "tests": s.tests,
                "errors": s.errors,
                "already_applied": s.already_applied,
                "found_vacancies": s.found_vacancies,
                "current_vacancy_title": s.current_vacancy_title,
                "current_vacancy_company": s.current_vacancy_company,
                "current_vacancy_idx": s.current_vacancy_idx,
                "total_vacancies": s.total_vacancies,
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
                "hh_interviews": s.hh_interviews,
                "hh_interviews_recent": s.hh_interviews_recent,
                "hh_viewed": s.hh_viewed,
                "hh_discards": s.hh_discards,
                "hh_not_viewed": s.hh_not_viewed,
                "hh_stats_updated": hh_updated_str,
                "hh_stats_loading": s.hh_stats_loading,
                "hh_interviews_list": s.hh_interviews_list[:20],
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
                "llm_enabled": s.llm_enabled,
            })

        # Временные браузерные сессии добавляются после обычных аккаунтов
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
                    "status": s.status,
                    "status_detail": s.status_detail,
                    "sent": s.sent,
                    "total_applied": len((_cache_applied or {}).get(s.acc["name"], {})),
                    "tests": s.tests,
                    "errors": s.errors,
                    "already_applied": s.already_applied,
                    "found_vacancies": s.found_vacancies,
                    "current_vacancy_title": s.current_vacancy_title,
                    "current_vacancy_company": s.current_vacancy_company,
                    "current_vacancy_idx": s.current_vacancy_idx,
                    "total_vacancies": s.total_vacancies,
                    "salary_skipped": s.salary_skipped,
                    "questionnaire_sent": s.questionnaire_sent,
                    "limit_exceeded": s.limit_exceeded,
                    "paused": s.paused,
                    "next_resume_touch": nrt,
                    "resume_touch_status": s.resume_touch_status,
                    "resume_touch_enabled": s.resume_touch_enabled,
                    "hh_interviews": s.hh_interviews,
                    "hh_interviews_recent": s.hh_interviews_recent,
                    "hh_viewed": s.hh_viewed,
                    "hh_discards": s.hh_discards,
                    "hh_not_viewed": s.hh_not_viewed,
                    "hh_stats_updated": ts_hh_updated_str,
                    "hh_stats_loading": s.hh_stats_loading,
                    "hh_interviews_list": s.hh_interviews_list[:20],
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
                    "llm_enabled": s.llm_enabled,
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
                    "hh_not_viewed": 0, "hh_stats_updated": "", "hh_stats_loading": False,
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
                })

        storage_stats = get_stats()

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
                "questionnaire_templates": CONFIG.questionnaire_templates,
                "questionnaire_default_answer": CONFIG.questionnaire_default_answer,
                "letter_templates": CONFIG.letter_templates,
                "url_pool": CONFIG.url_pool,
                "llm_enabled": CONFIG.llm_enabled,
                "llm_auto_send": CONFIG.llm_auto_send,
                "llm_fill_questionnaire": CONFIG.llm_fill_questionnaire,
                "llm_use_cover_letter": CONFIG.llm_use_cover_letter,
                "llm_use_resume": CONFIG.llm_use_resume,
                "llm_model": CONFIG.llm_model,
                "llm_base_url": CONFIG.llm_base_url,
                # Не включаем llm_api_key в snapshot из соображений безопасности
                "llm_profiles": [
                    {"name": p.get("name", ""), "base_url": p.get("base_url", ""),
                     "model": p.get("model", ""), "enabled": p.get("enabled", True)}
                    for p in (CONFIG.llm_profiles or [])
                ],
                "llm_profile_mode": CONFIG.llm_profile_mode,
            },
            "global_stats": {
                "total_sent": sum(s.sent for s in self.account_states),
                "total_tests": sum(s.tests for s in self.account_states),
                "total_errors": sum(s.errors for s in self.account_states),
                "total_found": sum(s.found_vacancies for s in self.account_states),
                "storage_total": storage_stats["total"],
                "storage_tests": storage_stats["tests"],
            },
            "vacancy_queues": {
                s.short: {
                    "remaining": max(0, len(s.vacancies_queue) - s.current_vacancy_idx),
                    "next": s.vacancies_queue[s.current_vacancy_idx: s.current_vacancy_idx + 5]
                    if s.vacancies_queue
                    else [],
                }
                for s in self.account_states
            },
        }

    def _run_account_worker(self, idx: int, state: AccountState) -> None:
        """Thread worker for an account — mirrors TUI run_account_worker logic"""
        acc = state.acc

        while not self._stop_event.is_set() and not state._deleted:
            # Глобальная пауза и пауза аккаунта
            while (self.paused or state.paused) and not self._stop_event.is_set() and not state._deleted:
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
                    self._add_log(state.short, state.color, "📤 Поднимаю резюме...", "info")
                    success, message = touch_resume(acc)

                    if success:
                        state.resume_touch_status = "✅ Поднято!"
                        state.last_resume_touch = now
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
                            f"📤 {message}. Повтор в {state.next_resume_touch.strftime('%H:%M')}",
                            "warning",
                        )

            # === ПРОВЕРКА ЛИМИТА ===
            if state.limit_exceeded:
                if state.limit_reset_time and now >= state.limit_reset_time:
                    state.status = "checking"
                    state.status_detail = "Проверка сброса лимита..."
                    self._add_log(state.short, state.color, "🔍 Проверяю сброс лимита...", "info")

                    if not check_limit(acc):
                        state.limit_exceeded = False
                        state.limit_reset_time = None
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
                    time.sleep(30)
                    continue

            # === СБОР ВАКАНСИЙ (ПАРАЛЛЕЛЬНО) ===
            # Если у аккаунта нет своих URL — используем глобальный пул
            effective_urls = acc.get("urls") or [_url_entry(u)["url"] for u in CONFIG.url_pool]
            state.total_urls = len(effective_urls)

            state.status = "collecting"
            state.status_detail = "Начинаю параллельный сбор..."
            state.cycle_start_time = now
            state.vacancies_by_url = {}
            state.vacancy_meta = {}  # Сброс метаданных вакансий для нового цикла

            self._add_log(
                state.short, state.color,
                f"📥 Параллельный сбор: {len(effective_urls)} URL × {CONFIG.pages_per_url} стр",
                "info",
            )

            results_by_url, salary_map = asyncio.run(self._collect_all_urls_parallel(state))
            state.vacancy_salaries = salary_map

            all_vacancies = []
            for url in effective_urls:
                url_vacancies = results_by_url.get(url, set())
                state.vacancies_by_url[url] = len(url_vacancies)
                all_vacancies.extend(url_vacancies)

                query = extract_search_query(url)
                if url_vacancies:
                    self._add_log(state.short, state.color, f"📊 {query}: {len(url_vacancies)}", "info")
            # Сохраняем статистику по URL для снапшота
            state.url_stats = dict(state.vacancies_by_url)

            unique_vacancies = set(all_vacancies)
            total_collected = len(unique_vacancies)

            self._add_log(
                state.short, state.color,
                f"📊 Всего собрано: {len(all_vacancies)} ({total_collected} уникальных)",
                "info",
            )

            if not unique_vacancies:
                state.status = "waiting"
                state.status_detail = "Нет вакансий"
                state.wait_until = now + timedelta(minutes=2)
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

            for vid in unique_vacancies:
                if is_applied(acc["name"], vid):
                    already_count += 1
                    state.already_applied += 1
                elif is_test(vid) and not state.apply_tests:
                    # Пропускаем тест-вакансии только если apply_tests выключен
                    test_count += 1
                    state.tests += 1
                elif CONFIG.min_salary > 0:
                    sal = salary_map.get(vid)
                    if sal is None or sal < CONFIG.min_salary:
                        salary_skipped += 1
                        state.salary_skipped += 1
                    else:
                        filtered.append(vid)
                else:
                    filtered.append(vid)

            sal_msg = f", 💰 зарплата {salary_skipped}" if CONFIG.min_salary > 0 else ""
            self._add_log(
                state.short, state.color,
                f"🔍 Фильтрация: ✅ уже {already_count}, 🧪 тест {test_count}{sal_msg}, 🆕 новые {len(filtered)}",
                "info",
            )

            if not filtered:
                state.status = "waiting"
                state.status_detail = "Нет новых вакансий"
                state.wait_until = now + timedelta(minutes=2)
                self._add_log(
                    state.short, state.color,
                    f"⚠️ Все вакансии уже обработаны ({already_count} откликов, {test_count} тестов), пауза 2 мин",
                    "warning",
                )
                time.sleep(120)
                continue

            random.shuffle(filtered)
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

                if len(batch) > 1:
                    self._add_log(
                        state.short, state.color,
                        f"📤 Пакет {len(batch)} откликов: {', '.join(batch[:3])}{'...' if len(batch) > 3 else ''}",
                        "info",
                    )

                def _make_send_batch(b):
                    async def send_batch():
                        tasks = [send_response_async(acc, vid) for vid in b]
                        return await asyncio.gather(*tasks, return_exceptions=True)
                    return send_batch

                results = asyncio.run(_make_send_batch(batch)())

                for j, (vid, result_data) in enumerate(zip(batch, results)):
                    if isinstance(result_data, Exception):
                        state.errors += 1
                        state.consecutive_errors += 1
                        err_msg = str(result_data)[:60]
                        self._add_log(state.short, state.color, f"❌ {vid}: {err_msg}", "error")
                        self._add_acc_event(state, "❌", "error", vid, "", err_msg)
                        self._check_auto_pause(state)
                        continue

                    result, info = result_data
                    state.current_vacancy_id = vid

                    if result == "sent":
                        state.sent += 1
                        state.consecutive_errors = 0  # сброс счётчика ошибок
                        # Дополняем info мета-данными из поиска если API не вернул title
                        if not info.get("title"):
                            meta_fb = state.vacancy_meta.get(vid, {})
                            info = {**meta_fb, **info}
                        add_applied(acc["name"], vid, info)

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

                        if not state.apply_tests:
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
                                state.current_vacancy_title = title
                                state.current_vacancy_company = company
                                state.action_history.append(f"📝 {display_title[:25]}")
                                self._add_response(state, vid, title, company, "sent")
                                self._add_log(state.short, state.color,
                                              f"📝 Опрос пройден: {display_title}", "success")
                                q_info_full = {**state.vacancy_meta.get(vid, {}), **info}
                                add_applied(acc["name"], vid, q_info_full)
                                answer_preview = CONFIG.questionnaire_default_answer[:50]
                                self._add_acc_event(state, "📝", "questionnaire",
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
                                              f"🚫 ЛИМИТ при опросе! Повторная попытка в {state.limit_reset_time.strftime('%H:%M')}",
                                              "error")
                                break
                            else:
                                # Не удалось — сохраняем как тест
                                state.tests += 1
                                add_test_vacancy(vid, title, company,
                                                 acc["name"], acc.get("resume_hash", ""))
                                state.action_history.append(f"🧪 {display_title[:25]}")
                                self._add_response(state, vid, title, company, "test")
                                self._add_log(state.short, state.color,
                                              f"🧪 Тест (не пройден): {display_title}", "warning")
                                self._add_acc_event(state, "🧪", "test",
                                                    title or vid, company, "не пройден")

                    elif result == "already":
                        state.already_applied += 1
                        already_info = state.vacancy_meta.get(vid, {})
                        add_applied(acc["name"], vid, already_info if already_info else None)
                        state.action_history.append(f"🔄 {vid}")
                        self._add_response(state, vid, "", "", "already")

                    elif result == "limit":
                        state.limit_exceeded = True
                        state.limit_reset_time = datetime.now() + timedelta(
                            minutes=CONFIG.limit_check_interval
                        )
                        state.status = "limit"
                        state.status_detail = f"Проверка в {state.limit_reset_time.strftime('%H:%M')}"
                        self._add_log(
                            state.short, state.color,
                            f"🚫 ЛИМИТ! Повторная попытка в {state.limit_reset_time.strftime('%H:%M')}",
                            "error",
                        )
                        break

                    elif result == "auth_error":
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
            state.current_vacancy_id = ""
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
                state.wait_until = datetime.now() + timedelta(seconds=CONFIG.pause_between_cycles)
                self._add_log(
                    state.short, state.color,
                    f"⏳ Цикл завершён, пауза {CONFIG.pause_between_cycles}с",
                    "info",
                )
                time.sleep(CONFIG.pause_between_cycles)

    async def _collect_all_urls_parallel(self, state: AccountState) -> tuple:
        """
        Параллельный сбор вакансий со ВСЕХ URL и страниц одновременно.
        Возвращает (results_by_url: dict[url, set[ids]], salary_map: dict[vid, int|None])
        """
        acc = state.acc
        headers = get_headers(acc["cookies"]["_xsrf"])
        sem = asyncio.Semaphore(CONFIG.max_concurrent * 3)

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=CONFIG.max_concurrent * 3)

        all_tasks = []
        url_pages = _url_pages_map()
        acc_url_pages = acc.get("url_pages", {})  # Переопределение на уровне аккаунта
        effective_urls = acc.get("urls") or [_url_entry(u)["url"] for u in CONFIG.url_pool]
        for url_idx, url in enumerate(effective_urls):
            pages = acc_url_pages.get(url) or url_pages.get(url, CONFIG.pages_per_url)
            sep = "&" if "?" in url else "?"
            for page in range(pages):
                page_url = f"{url}{sep}page={page}"
                all_tasks.append((url_idx, url, page, page_url))

        total_tasks = len(all_tasks)
        results_by_url = {url: [] for url in effective_urls}
        salary_map = {}
        completed = 0

        async with aiohttp.ClientSession(
            headers=headers, cookies=acc["cookies"], connector=connector
        ) as session:
            async def fetch_one(url_idx, url, page, page_url):
                nonlocal completed
                html = await fetch_page(session, page_url, sem)
                completed += 1
                state.current_url_idx = url_idx
                state.current_url = url
                state.current_page = page + 1
                state.status_detail = f"Загрузка {completed}/{total_tasks}"
                if html and _is_login_page(html):
                    state.cookies_expired = True
                    return url, set(), {}, {}
                if html:
                    ids = parse_ids(html)
                    salaries = parse_salaries(html, ids)
                    meta = parse_vacancy_meta(html)
                    return url, ids, salaries, meta
                return url, set(), {}, {}

            tasks = [
                fetch_one(url_idx, url, page, page_url)
                for url_idx, url, page, page_url in all_tasks
            ]
            task_results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in task_results:
                if isinstance(result, Exception):
                    log_debug(f"❌ Ошибка при загрузке: {result}")
                    continue
                url, ids, salaries, meta = result
                results_by_url[url].extend(ids)
                salary_map.update(salaries)
                state.vacancy_meta.update(meta)

        return {url: set(ids) for url, ids in results_by_url.items()}, salary_map

    def _process_llm_replies(self, state: AccountState) -> None:
        """Check recent unread negotiations for employer messages and auto-reply using LLM."""
        if not state.llm_enabled:
            return
        # Неблокирующий режим: если аккаунт уже обрабатывается другим потоком, пропускаем
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

        # Синхронизируем _llm_no_chat из сохранённой БД: учитываем 409 из прошлых сессий
        state._llm_no_chat.update(get_no_chat_neg_ids())

        # Загружаем свежие страницы чатов, отсортированные по последней активности. Чаты, где нужен ответ,
        # обычно находятся вверху списка, потому что работодатель только что написал.
        self._add_log(state.short, state.color, "🤖 LLM: загружаю список чатов…", "info")
        log_debug(f"LLM [{state.short}]: загружаю чат-лист")
        items_by_id, display_info, cur_pid = _fetch_chat_list(state.acc, max_pages=3)
        log_debug(f"LLM [{state.short}]: чат-лист загружен, {len(items_by_id)} чатов")

        # Обрабатываем элементы, где нужен ответ: тип NEGOTIATION, непрочитано, от работодателя, не отказ
        # Не фильтруем по interview_ids: чаты отсортированы по свежей активности, старые ID интервью
        # глубоко в списке на 10000 элементов и всё равно не попадут на первые страницы
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
            # Ранняя проверка: известный 409 из БД или текущей сессии
            if item_id in state._llm_no_chat:
                skipped_locked += 1
                log_debug(f"LLM [{state.short}] {item_id}: 409-закрыт, пропуск кандидата")
                continue
            # Ранняя проверка: чат закрыт по тексту/флагам, работодатель отключил сообщения или доступ только по приглашению
            if _check_chat_locked(item):
                skipped_locked += 1
                log_debug(f"LLM [{state.short}] {item_id}: чат заблокирован, пропуск кандидата «{last_text}»")
                continue
            if unread == 0:
                if from_employer and not wf:
                    # unread=0, но последнее от работодателя: пользователь прочитал в браузере,
                    # но бот ещё не отвечал. Проверяем по dedup: если last_msg_id ещё
                    # не в llm_replied_msgs — добавляем в кандидаты.
                    last_msg_id_early = str((item.get("lastMessage") or {}).get("id", ""))
                    key_early = (str(item_id), last_msg_id_early)
                    if key_early not in state.llm_replied_msgs:
                        log_debug(f"LLM [{state.short}] {item_id}: unread=0 но от работодателя, не отвечали — добавляю кандидатом: «{last_text}»")
                        # не skipping — fall through to candidates
                    else:
                        skipped_read += 1
                        log_debug(f"LLM [{state.short}] {item_id}: unread=0, от работодателя, уже отвечали, пропуск: «{last_text}»")
                        continue
                else:
                    skipped_read += 1
                    continue
            if cur_pid and sender_id == cur_pid:
                skipped_ours += 1
                log_debug(f"LLM [{state.short}] {item_id}: unread={unread}, последнее наше, пропуск")
                continue
            if wf:
                wf_id = wf.get("id", "") if isinstance(wf, dict) else ""
                # Числовой wf.id = просто внутренняя ссылка, сообщение реальное
                # Строковый wf.id = тип системного события (REJECTION, APPLICATION, etc.) = пропускаем
                if isinstance(wf_id, str) and wf_id:
                    skipped_system += 1
                    log_debug(f"LLM [{state.short}] {item_id}: unread={unread}, системное событие wf={wf_id!r}, пропуск")
                    continue
                # Числовой wf.id — продолжаем обработку как реальное сообщение
                log_debug(f"LLM [{state.short}] {item_id}: unread={unread}, wf.id={wf_id!r} (числовой, реальное сообщение)")
            # Логируем сырые поля элемента, чтобы находить новые признаки закрытого чата
            log_debug(f"LLM [{state.short}] {item_id}: ✅ кандидат unread={unread}, от={sender_id}, «{last_text}» | "
                      f"keys={list(item.keys())} canSend={item.get('canSendMessage')} state={item.get('state')} "
                      f"permissions={item.get('permissions')} actions={item.get('actions')}")
            candidates.append(item_id)

        log_debug(f"LLM [{state.short}]: {len(candidates)} кандидатов (прочитанных: {skipped_read}, наших: {skipped_ours}, системных: {skipped_system})")
        if not candidates:
            self._add_log(state.short, state.color,
                f"🤖 LLM: нет новых сообщений (прочит.: {skipped_read}, наших: {skipped_ours}, сист.: {skipped_system}, закрыт: {skipped_locked})", "info")
            return

        self._add_log(state.short, state.color, f"🤖 LLM: {len(candidates)} чатов требуют ответа", "info")

        for i, neg_id in enumerate(candidates[:15]):  # Ограничение до 15 за цикл
            # Проверяем флаг в начале каждой итерации — пользователь мог выключить LLM во время цикла
            if not state.llm_enabled or not CONFIG.llm_enabled:
                self._add_log(state.short, state.color, f"🤖 LLM: выключен в процессе цикла, прерываю", "warning")
                break
            try:
                # Ранний пропуск чатов, подтверждённо закрытых через 409 в этой сессии
                if neg_id in state._llm_no_chat:
                    item = items_by_id[neg_id]
                    info = display_info.get(str(neg_id), {})
                    emp = (info.get("subtitle") or neg_id).strip(" ,")[:25]
                    self._add_log(state.short, state.color,
                        f"🤖 [{emp}] 🔒 переписка закрыта, пропуск", "warning", neg_id=neg_id)
                    continue

                item = items_by_id[neg_id]
                thread = _build_thread_from_chat_item(item, display_info, cur_pid, neg_id)
                employer_short = thread.get("employer_name", neg_id)[:25]
                if thread.get("error"):
                    self._add_log(state.short, state.color, f"🤖 [{employer_short}] ошибка треда: {thread['error']}", "error", neg_id=neg_id)
                    continue

                employer = thread.get("employer_name", neg_id)[:35]
                employer_msg = thread.get("last_employer_msg", "")
                vacancy_title = thread.get("vacancy_title", "")

                # Если чат прошёл ранний фильтр (unread=0 но от работодателя, не отвечали),
                # принудительно ставим needs_reply=True — _build_thread_from_chat_item
                # возвращает False из-за unread=0, но мы уже проверили dedup выше.
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

                # Чат закрыт: работодатель отключил сообщения или доступ только по приглашению; пропускаем навсегда
                if thread.get("chat_locked"):
                    lock_reason = thread["chat_locked"]
                    log_debug(f"LLM [{state.short}] {neg_id}: переписка недоступна — {lock_reason!r}")
                    self._add_log(state.short, state.color,
                        f"🤖 [{employer_short}] 🔒 переписка недоступна, пропуск", "warning", neg_id=neg_id)
                    state.llm_replied_msgs.add((neg_id, "locked"))  # Постоянный пропуск
                    continue

                # Сохраняем данные переписки в БД переговоров
                upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                 employer=employer, vacancy_title=vacancy_title,
                                 employer_last_msg=employer_msg if employer_msg else None,
                                 needs_reply=bool(thread.get("needs_reply")))

                if not thread.get("needs_reply"):
                    log_debug(f"LLM [{state.short}] {neg_id}: ответ не нужен (последнее сообщение — от соискателя)")
                    self._add_log(state.short, state.color, f"🤖 [{employer_short}] последнее сообщение наше, пропуск", "info", neg_id=neg_id)
                    continue
                last_msg_id = thread["last_msg_id"]
                key = (neg_id, last_msg_id)
                # Дедупликация на уровне аккаунта: предотвращает повторы в той же сессии
                if key in state.llm_replied_msgs:
                    log_debug(f"LLM [{state.short}] {neg_id}: уже отвечали на msg {last_msg_id}")
                    self._add_log(state.short, state.color, f"🤖 [{employer_short}] уже отвечали в этой сессии, пропуск", "info", neg_id=neg_id)
                    continue
                # Временный пропуск для преходящих ошибок: LLM API или сеть при отправке
                _skip_until = state._llm_temp_skip.get(key, 0)
                if time.time() < _skip_until:
                    mins = max(1, int((_skip_until - time.time()) / 60))
                    self._add_log(state.short, state.color,
                        f"🤖 [{employer_short}] повтор через ~{mins}м (ошибка в предыдущем цикле)", "info", neg_id=neg_id)
                    log_debug(f"LLM [{state.short}] {neg_id}: temp_skip до {_skip_until:.0f}")
                    continue
                # Глобальная дедупликация по (cur_pid, neg_id, last_msg_id): предотвращает двойную отправку
                # когда два аккаунта используют одного HH-пользователя (один cur_pid)
                global_key = (cur_pid, neg_id, last_msg_id)
                with self._llm_sent_lock:
                    if global_key in self._llm_sent_global:
                        log_debug(f"LLM [{state.short}] {neg_id}: уже отправлено другим аккаунтом (pid={cur_pid})")
                        self._add_log(state.short, state.color, f"🤖 [{employer_short}] уже отправлено другим аккаунтом, пропуск", "info")
                        state.llm_replied_msgs.add(key)
                        continue

                progress = f"[{i+1}/{min(len(candidates),15)}]"
                self._add_log(state.short, state.color,
                    f"🤖 {progress} [{employer_short}]: «{employer_msg[:50]}»", "info", neg_id=neg_id)
                log_debug(f"LLM [{state.short}] {progress} {neg_id} ({employer_short}): загружаю историю чата")
                cover_letter = state.acc.get("letter", "") if CONFIG.llm_use_cover_letter else ""
                # Загружаем резюме для контекста LLM
                if CONFIG.llm_use_resume:
                    rh = state.acc.get("resume_hash", "")
                    _cached = rh and rh in _resume_cache and (time.time() - _resume_cache[rh][1] < _RESUME_CACHE_TTL)
                    resume_text = fetch_resume_text(state.acc)
                    if resume_text:
                        src = "кэш" if _cached else "загружено"
                        self._add_log(state.short, state.color,
                            f"🤖 📄 Резюме в контексте LLM ({src}, {len(resume_text)} симв.)", "info", neg_id=neg_id)
                    else:
                        self._add_log(state.short, state.color,
                            f"🤖 📄 Резюме не удалось загрузить — LLM работает без него", "warning", neg_id=neg_id)
                else:
                    resume_text = ""
                # Загружаем полную историю переписки, чтобы у LLM был весь контекст
                full_history = _fetch_chat_history(state.acc, neg_id, max_messages=20)
                conversation = full_history if full_history else thread["messages"]
                # Если в истории нет реального сообщения от работодателя — не отвечаем.
                # Случай 1: только системные события ("Отклик на вакансию" и т.п.) — history пустая
                # Случай 2: history есть, но последнее сообщение от нас (уже ответили)
                has_employer_msg = any(m.get("sender") == "employer" for m in conversation)
                last_real_sender = conversation[-1].get("sender") if conversation else None
                if not has_employer_msg:
                    log_debug(f"LLM [{state.short}] {neg_id}: нет реальных сообщений работодателя (только системные), пропуск")
                    state.llm_replied_msgs.add(key)  # не повторять этот триггер
                    continue
                if last_real_sender == "applicant":
                    log_debug(f"LLM [{state.short}] {neg_id}: последнее реальное сообщение наше — уже ответили, пропуск")
                    state.llm_replied_msgs.add(key)
                    continue
                log_debug(f"LLM [{state.short}] {neg_id}: история {len(conversation)} сообщений, резюме {len(resume_text)} симв., отправляю в LLM")
                self._add_log(state.short, state.color,
                    f"🤖 {progress} [{employer_short}]: история {len(conversation)} сообщ., жду LLM…", "info", neg_id=neg_id)
                decision = resolve_chat_answer(
                    conversation, employer_name=thread.get("employer_name", ""),
                    cover_letter=cover_letter, resume_text=resume_text,
                    vacancy_title=vacancy_title,
                    vacancy_data={"title": vacancy_title, "company": employer},
                )
                reply_text = decision.get("answer", "") or _fallback_answer()
                answer_source = decision.get("source", "fallback")
                record_answer_history(
                    kind="chat",
                    source=answer_source,
                    question=decision.get("question", employer_msg),
                    answer=reply_text,
                    account=state.short,
                    neg_id=neg_id,
                    vacancy_title=vacancy_title,
                    company=employer,
                    metadata={**(decision.get("metadata") or {}), "last_msg_id": last_msg_id},
                )
                if not reply_text:
                    self._add_log(state.short, state.color, f"🤖 [{employer_short}] LLM вернул пустой ответ, повтор через 30м", "warning", neg_id=neg_id)
                    log_debug(f"LLM [{state.short}] {neg_id}: пустой ответ от LLM, ставим temp_skip 30м")
                    state._llm_temp_skip[key] = time.time() + 1800  # Повтор через 30 минут
                    continue
                log_debug(f"LLM [{state.short}] {neg_id}: ответ получен ({len(reply_text)} симв.), отправляю")

                ts = datetime.now().strftime("%d.%m %H:%M")

                if CONFIG.llm_auto_send:
                    # Повторно проверяем глобальную дедупликацию прямо перед отправкой: атомарная бронь
                    with self._llm_sent_lock:
                        if global_key in self._llm_sent_global:
                            log_debug(f"LLM [{state.short}] {neg_id}: другой поток уже отправил (pid={cur_pid}), пропуск")
                            self._add_log(state.short, state.color, f"🤖 [{employer_short}] другой аккаунт уже отправил, пропуск", "info")
                            state.llm_replied_msgs.add(key)
                            continue
                        # Бронируем слот до отправки, чтобы параллельные потоки его видели
                        self._llm_sent_global.add(global_key)
                    self._add_log(state.short, state.color,
                        f"🤖 [{employer_short}] отправляю: «{reply_text[:60]}»", "info", neg_id=neg_id)
                    log_debug(f"LLM [{state.short}] {neg_id}: отправляю сообщение в chatik")
                    ok = send_negotiation_message(state.acc, neg_id, reply_text, topic_id=thread.get("topic_id", ""))
                    if ok == "chat_not_found":
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                        state.llm_replied_msgs.add(key)
                        state._llm_no_chat.add(neg_id)  # Постоянно: этот neg_id возвращает 409
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         employer=employer, vacancy_title=vacancy_title,
                                         chat_not_found=True)  # Сохраняем, чтобы пережить перезапуски
                        self._add_log(state.short, state.color,
                            f"🤖 [{employer_short}] 🔒 переписка закрыта (409), пропуск", "warning", neg_id=neg_id)
                        continue
                    if ok:
                        state.llm_replied_msgs.add(key)
                        replied += 1
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         llm_reply=reply_text, llm_sent=True,
                                         answer_source=answer_source,
                                         answer_metadata=decision.get("metadata", {}),
                                         conversation=conversation)
                        self._add_log(state.short, state.color,
                            f"🤖 Авто-ответ → {employer}: {reply_text[:60]}…", "success", neg_id=neg_id)
                        self.llm_log.appendleft({
                            "time": ts, "acc": state.short, "color": state.color,
                            "employer": employer, "vacancy_title": vacancy_title,
                            "neg_id": neg_id, "employer_msg": employer_msg,
                            "bot_reply": reply_text, "sent": True, "source": answer_source,
                        })
                    else:
                        # Освобождаем глобальную бронь, чтобы другой аккаунт мог повторить
                        with self._llm_sent_lock:
                            self._llm_sent_global.discard(global_key)
                        # Используем temp_skip на 30 минут вместо постоянной отметки: ошибка отправки может быть временной
                        state._llm_temp_skip[key] = time.time() + 1800  # Повтор через 30 минут
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         llm_reply=reply_text, llm_sent=False,
                                         answer_source=answer_source,
                                         answer_metadata=decision.get("metadata", {}),
                                         conversation=conversation)
                        self._add_log(state.short, state.color,
                            f"🤖 Черновик (ошибка отправки, повтор ~30м) → {employer}: {reply_text[:60]}…", "warning", neg_id=neg_id)
                        self.llm_log.appendleft({
                            "time": ts, "acc": state.short, "color": state.color,
                            "employer": employer, "vacancy_title": vacancy_title,
                            "neg_id": neg_id, "employer_msg": employer_msg,
                            "bot_reply": reply_text, "sent": False, "source": answer_source,
                        })
                else:
                    state.llm_replied_msgs.add(key)
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                     llm_reply=reply_text, llm_sent=False,
                                     answer_source=answer_source,
                                     answer_metadata=decision.get("metadata", {}),
                                     conversation=conversation)
                    self._add_log(state.short, state.color,
                        f"🤖 Черновик [{employer}]: {reply_text[:80]}…", "info", neg_id=neg_id)
                    self.llm_log.appendleft({
                        "time": ts, "acc": state.short, "color": state.color,
                        "employer": employer, "vacancy_title": vacancy_title,
                        "neg_id": neg_id, "employer_msg": employer_msg,
                        "bot_reply": reply_text, "sent": False, "source": answer_source,
                    })

                time.sleep(3)  # Ограничение частоты между сообщениями
            except Exception as e:
                log_debug(f"_process_llm_replies {neg_id}: {e}")
                # Освобождаем глобальную бронь дедупликации для neg_id, если она была
                # создана до исключения и ещё не была очищена
                try:
                    with self._llm_sent_lock:
                        to_remove = {gk for gk in self._llm_sent_global if gk[1] == neg_id}
                        self._llm_sent_global -= to_remove
                except Exception:
                    pass

        if replied:
            log_debug(f"LLM auto-reply [{state.short}]: {replied} ответов отправлено")

    def _fetch_hh_stats_worker(self, idx: int, state: AccountState) -> None:
        """Thread worker for HH stats polling"""
        HH_STATS_INTERVAL = 900  # 15 minutes

        while not self._stop_event.is_set():
            state.hh_stats_loading = True
            try:
                # Статистика переговоров
                stats = fetch_hh_negotiations_stats(state.acc)
                if stats.get("auth_error"):
                    state.cookies_expired = True
                    self._add_log(
                        state.short, state.color,
                        "⚠️ Куки протухли! (HH stats) Обновите куки.", "error",
                    )
                old_interviews = state.hh_interviews
                state.hh_interviews = stats["interview"]
                state.hh_interviews_recent = stats["recent_interview"]
                state.hh_viewed = stats["viewed"]
                state.hh_not_viewed = stats["not_viewed"]
                state.hh_discards = stats["discard"]
                state.hh_interviews_list = stats["interviews_list"]
                state.hh_interview_neg_ids = stats.get("neg_ids", [])

                # Сохраняем переговоры в БД: neg_id -> работодатель из текста interviews_list
                for neg_id in state.hh_interview_neg_ids:
                    upsert_interview(neg_id, acc=state.short, acc_color=state.color)
                # Пытаемся дополнить работодателя/вакансию из interviews_list, если количество совпало
                if len(state.hh_interview_neg_ids) == len(stats["interviews_list"]):
                    for neg_id, item in zip(state.hh_interview_neg_ids, stats["interviews_list"]):
                        parts = item.get("text", "").rsplit(" ", 1)
                        upsert_interview(neg_id, acc=state.short, acc_color=state.color,
                                         vacancy_title=item.get("text", ""))

                # Возможные офферы
                offers = fetch_hh_possible_offers(state.acc)
                state.hh_possible_offers = offers

                # Статистика резюме (views, shows, invitations, touch timer)
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

                # История просмотров резюме
                state.resume_view_history = fetch_resume_view_history(state.acc, limit=100)

                state.hh_stats_updated = datetime.now()

                if old_interviews > 0 and stats["interview"] > old_interviews:
                    new_count = stats["interview"] - old_interviews
                    self._add_log(
                        state.short, state.color,
                        f"🎯 НОВОЕ ПРИГЛАШЕНИЕ! (+{new_count} интервью)",
                        "success",
                    )

                log_debug(
                    f"HH stats {state.short}: {stats['interview']} интервью, "
                    f"{rs['views']} просмотров резюме, {rs['new_invitations_total']} новых инвайтов"
                )

                # LLM-автоответы
                _neg_count = len(state.hh_interview_neg_ids)
                if not CONFIG.llm_enabled:
                    log_debug(f"LLM [{state.short}]: пропуск — глобально выключено")
                elif not state.llm_enabled:
                    log_debug(f"LLM [{state.short}]: пропуск — выключено для аккаунта")
                elif not _neg_count:
                    self._add_log(state.short, state.color, "🤖 LLM: нет переговоров в статусе Интервью", "info")
                else:
                    self._add_log(state.short, state.color, f"🤖 LLM: проверяю {_neg_count} переговоров…", "info")
                    self._process_llm_replies(state)
            except Exception as e:
                log_debug(f"HH stats fetch error ({state.short}): {e}")
            finally:
                state.hh_stats_loading = False

            time.sleep(HH_STATS_INTERVAL)


# ============================================================
