"""
HH.ru web-flow client adapter (cookies hh.ru + chatik.hh.ru).

Phase 0: чистый адаптер поверх существующих функций
hh_chat / hh_apply / hh_negotiations / hh_resume / oauth.
Ноль новой логики — каждый метод делегирует в соответствующую
функцию модуля, подставляя self.acc первым аргументом.

Импортируются МОДУЛИ (а не функции) — тесты monkeypatch'ат атрибуты модулей.
"""

from app import hh_api, hh_chat, hh_apply, hh_negotiations, hh_resume, oauth
from app.hh_client import HHClient


class WebHHClient(HHClient):
    """Web-клиент: делегирует в существующие web-flow функции (cookies).

    Реализует полный контракт HHClient = HHClientBase + WebOnlyOps +
    MobileOnlyOps; из MobileOnlyOps fetch_counters кидает NotImplementedError
    (web-аналога GET /me нет).
    """

    # --- Группа A: переговоры / чат ---

    def fetch_negotiations(self, max_pages: int = 20) -> dict:
        return hh_negotiations.fetch_hh_negotiations_stats(self.acc, max_pages)

    def fetch_thread(self, neg_id: str) -> dict:
        return hh_chat.fetch_negotiation_thread(self.acc, neg_id)

    def send_message(self, neg_id: str, text: str, topic_id: str = "") -> bool | str:
        # фактически bool | "chat_not_found" (см. hh_chat.send_negotiation_message)
        return hh_chat.send_negotiation_message(self.acc, neg_id, text, topic_id)

    def fetch_chat_list(self, max_pages: int = 5) -> tuple:
        return hh_chat._fetch_chat_list(self.acc, max_pages)

    def fetch_chat_history(self, chat_id: str, max_messages: int = 20) -> list:
        return hh_chat._fetch_chat_history(self.acc, chat_id, max_messages)

    def fetch_quick_replies(self, chat_id: str, msg_id: str) -> list:
        return hh_chat.fetch_quick_replies(self.acc, chat_id, msg_id)

    def send_participant_action(self, chat_id: str, action_type: str = "TYPING") -> bool:
        return hh_chat.send_participant_action(self.acc, chat_id, action_type)

    def mark_chat_read(self, chat_id: str, message_id: str) -> bool:
        return hh_chat.mark_chat_read(self.acc, chat_id, message_id)

    def fetch_possible_offers(self) -> list:
        return hh_negotiations.fetch_hh_possible_offers(self.acc)

    def auto_decline_discards(self) -> int:
        return hh_negotiations.auto_decline_discards(self.acc)

    def fetch_negotiations_metadata(self) -> dict:
        return hh_negotiations.fetch_negotiations_metadata(self.acc)

    def fetch_employer_rating(self, employer_id) -> dict | None:
        return hh_negotiations.fetch_employer_rating(self.acc, employer_id)

    def fetch_employer_id_for_vacancy(self, vacancy_id) -> int | None:
        return hh_negotiations.fetch_employer_id_for_vacancy(self.acc, vacancy_id)

    def fetch_vacancy_owner_hr_hhid(self, vacancy_id) -> int | None:
        return hh_negotiations.fetch_vacancy_owner_hr_hhid(self.acc, vacancy_id)

    # --- Группа B: отклики (web-функции async — вызываем с await) ---

    async def submit_response(self, vid: str, letter_max_length: int | None = None) -> tuple:
        return await hh_apply.send_response_async(self.acc, vid, letter_max_length)

    async def fill_questionnaire(self, vid: str, vacancy_title: str = "", company: str = "") -> tuple:
        return await hh_apply.fill_and_submit_questionnaire(self.acc, vid, vacancy_title, company)

    def check_vacancy_before_apply(self, vid: str) -> dict:
        return hh_apply._check_vacancy_before_apply(self.acc, vid)

    def check_limit(self) -> bool:
        return hh_apply.check_limit(self.acc)

    def touch_resume(self) -> tuple:
        return hh_apply.touch_resume(self.acc)

    def fetch_related_vacancies(self, seed_vid: str, max_pages: int = 1) -> list:
        return hh_apply.fetch_related_vacancies(self.acc, seed_vid, max_pages)

    # --- Группа C: резюме ---

    def fetch_stats(self) -> dict:
        return hh_resume.fetch_resume_stats(self.acc)

    def fetch_resume(self) -> dict:
        return {"text": hh_resume.fetch_resume_text(self.acc), "source": "web"}

    def fetch_resume_view_history(self, limit: int = 50) -> list:
        return hh_resume.fetch_resume_view_history(self.acc, limit)

    def fetch_resume_views_aggregate(self) -> dict:
        return hh_resume.fetch_resume_views_aggregate(self.acc)

    def analyze_resume(self, extra_terms: list = None) -> dict:
        return hh_resume._analyze_resume(self.acc, extra_terms)

    def edit_resume_field(self, resume_hash: str, fields: dict) -> dict:
        return hh_resume._edit_resume_field(self.acc, resume_hash, fields)

    def set_job_search_status(self, status: str) -> dict:
        return hh_resume.set_job_search_status(self.acc, status)

    def fetch_account_diagnostics(self) -> dict:
        return hh_resume.fetch_account_diagnostics(self.acc)

    # --- Группа D: счётчики ---

    def fetch_counters(self) -> dict:
        raise NotImplementedError("phase 0: web-клиент не имеет аналога GET /me")

    # --- Группа E: OAuth-extras (уже Bearer api.hh.ru — делегируем в app.oauth) ---

    def fetch_saved_vacancy_searches(self) -> list:
        return oauth.fetch_saved_vacancy_searches(self.acc)

    def fetch_favorited_vacancies(self) -> list:
        return oauth.fetch_favorited_vacancies(self.acc)

    def fetch_blacklisted_vacancies(self) -> set:
        return oauth.fetch_blacklisted_vacancies(self.acc)

    def fetch_vacancy_details(self, vid: str) -> dict:
        return oauth.fetch_vacancy_details(self.acc, vid)

    def fetch_negotiations_today_count(self) -> dict:
        return oauth.fetch_negotiations_today_count(self.acc)

    def fetch_negotiations_statistic(self) -> dict:
        return oauth.fetch_negotiations_statistic(self.acc)

    def fetch_resume_status(self, force: bool = False) -> dict:
        if force:
            return oauth.fetch_resume_status(self.acc, force)
        return oauth.fetch_resume_status(self.acc)

    def fetch_employer_rating_oauth(self, employer_id: str) -> dict:
        return oauth.fetch_employer_rating(self.acc, employer_id)
    def search_vacancies(self, text: str, area_id=1, per_page: int = 20,
                         page: int = 0, filters=None) -> list:
        return hh_api.fetch_hh_vacancies(
            self.acc, text, area_id, per_page, page, filters)
