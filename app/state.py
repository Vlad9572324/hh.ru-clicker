"""
AccountState — per-account state object for the bot.
"""

import threading
from datetime import datetime
from collections import deque

from app.config import CONFIG
from app.storage import _cache_applied, _cache_lock


class AccountState:
    """Полное состояние аккаунта"""

    def __init__(self, acc_data: dict):
        self.acc = acc_data
        # Прокидываем cookies_lock в acc, чтобы hh_chat / hh_apply могли
        # сериализовать мутации acc["cookies"] (defensive — см. _ensure_chatik_cookies).
        # Сам lock создаётся ниже как self._cookies_lock; ставим shared reference.
        # Делаем это сразу до использования self чтобы AccountState видна.
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

        self.use_oauth = bool(acc_data.get("use_oauth", False))  # per-account OAuth toggle
        self.oauth_status = ""  # "active", "no_token", "error"

        self.daily_date = datetime.now().strftime("%Y-%m-%d")  # дата сброса счётчика
        # Count today's applies from persisted cache
        self.daily_sent = 0
        try:
            with _cache_lock:
                acc_applied = (_cache_applied or {}).get(self.name, {})
                today = self.daily_date
                for vid, info in acc_applied.items():
                    if isinstance(info, dict) and str(info.get("at", "")).startswith(today):
                        self.daily_sent += 1
        except Exception:
            pass
        self.hard_stopped = False  # жёсткая остановка (лимит или daily)

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
        self.schedule_skipped = 0     # Пропущено из-за формата работы
        self.vacancy_salaries = {}    # {vid: salary_from_rub_or_None}
        self.vacancy_schedules = {}   # {vid: set_of_schedule_ids}
        self.vacancy_meta = {}        # {vid: {title, company}} из HTML поиска
        self.questionnaire_sent = 0   # Успешно пройдено опросов
        self.inconsistent_skipped = 0  # Пропущено из-за несовпадения опыта

        self.hh_interviews = 0
        self.hh_interviews_recent = 0  # за последние 60 дней
        self.hh_viewed = 0
        self.hh_not_viewed = 0
        self.hh_discards = 0
        self.hh_interviews_list = []
        self.hh_possible_offers = []
        self.hh_stats_updated = None
        self.hh_stats_loading = False
        self.hh_unread_by_employer = 0  # count of negotiations where employer hasn't read our messages

        # Resume statistics
        self.resume_views_7d = 0
        self.resume_views_new = 0
        self.resume_shows_7d = 0
        self.resume_invitations_7d = 0
        self.resume_invitations_new = 0
        self.resume_next_touch_seconds = 0
        self.resume_free_touches = 0
        self.resume_global_invitations = 0
        self.resume_new_invitations_total = 0

        # Resume view history
        self.resume_view_history: list = []   # [{employer_id, name, date, vacancy}]

        # Per-account pause (new for web dashboard)
        self.paused = False
        self._deleted = False  # Set True to stop worker thread

        # Per-account event log (last 8 events shown on card)
        self.acc_event_log: deque = deque(maxlen=8)
        # Skip vacancies that require tests
        self.apply_tests: bool = bool(acc_data.get("apply_tests", False))
        # Consecutive errors counter for auto-pause
        self.consecutive_errors: int = 0
        # Per-URL vacancy counts from last collection cycle
        self.url_stats: dict = {}
        # Per-account per-URL pages override {url: pages}
        # (overrides global pool pages for this account)
        # stored in acc["url_pages"]
        # Cookie expiry flag — set when 401/403 or login redirect detected
        self.cookies_expired: bool = False

        # LLM auto-reply tracking
        self.llm_replied_msgs: set = set()   # {(neg_id, last_msg_id)} successfully replied (permanent per session)
        self._llm_temp_skip: dict = {}       # {(neg_id, last_msg_id): expiry_ts} — transient failure, retry after TTL
        self._llm_no_chat: set = set()       # {neg_id} chats that returned 409 (permanently closed/locked)
        self._llm_neg_failures: dict = {}    # {neg_id: count} — exception-counter for exponential backoff
        self.hh_interview_neg_ids: list = [] # negotiation IDs from last INTERVIEW fetch
        self.llm_enabled: bool = True        # per-account LLM toggle (overridden by global CONFIG.llm_enabled)
        self.llm_status: str = ""            # human-readable LLM status for dashboard display
        self.llm_replied_count: int = 0      # total replies sent this session
        self.llm_pending_chats: int = 0      # chats awaiting reply (from last scan)
        self._llm_lock = threading.Lock()    # prevents concurrent _process_llm_replies for this account
        self._msg_consecutive: dict = {}     # {neg_id: count} consecutive applicant messages without HR reply
        self._test_failures: dict = {}       # {vid: fail_count} questionnaire fill failures

        # Защита deques от race с broadcast loop (list(deque) при concurrent appendleft → RuntimeError).
        # Используется в _add_log/_add_response/_add_acc_event + snapshot reader.
        self._deque_lock = threading.Lock()
        # Защищает простые композитные read'ы (status+status_detail, hh-stats группой, vacancies_queue+idx).
        self._state_lock = threading.Lock()
        # Сериализует мутации acc["cookies"] между workers одного аккаунта.
        self._cookies_lock = threading.Lock()
        # Прокидываем lock в сам acc dict — чтобы hh_chat._ensure_chatik_cookies
        # мог найти его без знания о AccountState.
        self.acc["_cookies_lock"] = self._cookies_lock
        # Reason for pause — manual vs auto vs limit — чтобы midnight reset не сбрасывал manual pause.
        self.paused_reason: str = ""  # "", "manual", "auto_errors", "limit"
