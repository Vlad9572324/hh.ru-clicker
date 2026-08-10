"""
MobileHHClient — skeleton mobile-клиента (api.hh.ru, OAuth Bearer).

Phase 0: реально реализованы только
  - fetch_counters() — smoke-test абстракции (GET /me?with_user_statuses=true),
  - oauth-extras (группа E) — эти вызовы уже живут в app/oauth.py и работают
    через Bearer одинаково для web и mobile, поэтому просто делегируем туда.

Всё остальное — заглушки NotImplementedError("phase N: TODO mobile ..."):
  - phase 2: переговоры/чаты,
  - phase 3: отклики и vacancy-метаданные,
  - phase 4: резюме/статистика.
"""

import requests

from app import oauth
from app.hh_client import HHClient


class MobileHHClient(HHClient):
    """Mobile-flow реализация полного контракта HHClient (HHClientBase +
    WebOnlyOps + MobileOnlyOps): api.hh.ru через OAuth Bearer. Реально в
    Phase 0: fetch_counters (MobileOnlyOps) и OAuth-extras; остальное —
    NotImplementedError-заглушки."""

    def __init__(self, acc: dict):
        super().__init__(acc)

    # ── Phase 2: переговоры/чаты ──────────────────────────────────────────────

    def fetch_negotiations(self, max_pages: int = 20) -> dict:
        """Список переговоров + статистика (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile fetch_negotiations")

    def fetch_thread(self, neg_id: str) -> dict:
        """Тред переговоров по neg_id (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile fetch_thread")

    def send_message(self, neg_id: str, text: str, topic_id: str = "") -> bool | str:
        """Отправить сообщение в переговоры (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile send_message")

    def fetch_chat_list(self, max_pages: int = 5) -> tuple:
        """Список чатов (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile fetch_chat_list")

    def fetch_chat_history(self, chat_id: str, max_messages: int = 20) -> list:
        """История сообщений чата (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile fetch_chat_history")

    def fetch_quick_replies(self, chat_id: str, msg_id: str) -> list:
        """Быстрые ответы HH на сообщение (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile fetch_quick_replies")

    def send_participant_action(self, chat_id: str, action_type: str = "TYPING") -> bool:
        """Participant action (TYPING/NONE) в чат (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile send_participant_action")

    def mark_chat_read(self, chat_id: str, message_id: str) -> bool:
        """Отметить чат прочитанным до message_id (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile mark_chat_read")

    def fetch_possible_offers(self) -> list:
        """Возможные офферы (possible_job_offers) (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile fetch_possible_offers")

    def auto_decline_discards(self) -> int:
        """Автоотклонение DISCARD-переговоров (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile auto_decline_discards")

    def fetch_negotiations_metadata(self) -> dict:
        """Метаданные переговоров (phase 2)."""
        raise NotImplementedError("phase 2: TODO mobile fetch_negotiations_metadata")

    # ── Phase 3: отклики и vacancy-метаданные ─────────────────────────────────

    async def submit_response(self, vid: str, letter_max_length: int | None = None) -> tuple:
        """Отклик на вакансию (phase 3)."""
        raise NotImplementedError("phase 3: TODO mobile submit_response")

    async def fill_questionnaire(self, vid: str, vacancy_title: str = "", company: str = "") -> tuple:
        """Заполнение анкеты при отклике (phase 3).

        web-only: в ABC метод помечен как web-only (web:
        hh_apply.fill_and_submit_questionnaire), мобильной реализации пока не
        планируется. Fallback-политика для mobile-аккаунтов (делегировать в
        web-flow или оставить NotImplementedError) будет решена в Phase 3.
        """
        raise NotImplementedError("phase 3: TODO mobile fill_questionnaire")

    def check_vacancy_before_apply(self, vid: str) -> dict:
        """Пре-проверка вакансии перед откликом (phase 3)."""
        raise NotImplementedError("phase 3: TODO mobile check_vacancy_before_apply")

    def check_limit(self) -> bool:
        """Проверка дневного лимита откликов (phase 3)."""
        raise NotImplementedError("phase 3: TODO mobile check_limit")

    def touch_resume(self) -> tuple:
        """Поднять резюме (touch) (phase 3)."""
        raise NotImplementedError("phase 3: TODO mobile touch_resume")

    def fetch_related_vacancies(self, seed_vid: str, max_pages: int = 1) -> list:
        """Похожие вакансии для расширения пула (phase 3)."""
        raise NotImplementedError("phase 3: TODO mobile fetch_related_vacancies")

    def fetch_employer_rating(self, employer_id) -> dict | None:
        """Рейтинг работодателя (phase 3, vacancy-метаданные)."""
        raise NotImplementedError("phase 3: TODO mobile fetch_employer_rating")

    def fetch_employer_id_for_vacancy(self, vacancy_id) -> int | None:
        """employer_id по вакансии (phase 3, vacancy-метаданные)."""
        raise NotImplementedError("phase 3: TODO mobile fetch_employer_id_for_vacancy")

    def fetch_vacancy_owner_hr_hhid(self, vacancy_id) -> int | None:
        """HHID HR-а, владеющего вакансией (phase 3, vacancy-метаданные)."""
        raise NotImplementedError("phase 3: TODO mobile fetch_vacancy_owner_hr_hhid")

    # ── Phase 4: резюме/статистика ────────────────────────────────────────────

    def fetch_stats(self) -> dict:
        """Статистика резюме (phase 4)."""
        raise NotImplementedError("phase 4: TODO mobile fetch_stats")

    def fetch_resume(self) -> str:
        """Текст резюме (phase 4)."""
        raise NotImplementedError("phase 4: TODO mobile fetch_resume")

    def fetch_resume_view_history(self, limit: int = 50) -> list:
        """История просмотров резюме (phase 4)."""
        raise NotImplementedError("phase 4: TODO mobile fetch_resume_view_history")

    def fetch_resume_views_aggregate(self) -> dict:
        """Агрегированные просмотры резюме (phase 4)."""
        raise NotImplementedError("phase 4: TODO mobile fetch_resume_views_aggregate")

    def analyze_resume(self, extra_terms: list = None) -> dict:
        """Аудит резюме по ключевым словам (phase 4)."""
        raise NotImplementedError("phase 4: TODO mobile analyze_resume")

    def edit_resume_field(self, resume_hash: str, fields: dict) -> dict:
        """Редактирование полей резюме (phase 4)."""
        raise NotImplementedError("phase 4: TODO mobile edit_resume_field")

    def set_job_search_status(self, status: str) -> dict:
        """Смена статуса поиска работы (phase 4)."""
        raise NotImplementedError("phase 4: TODO mobile set_job_search_status")

    def fetch_account_diagnostics(self) -> dict:
        """Диагностика аккаунта (phase 4)."""
        raise NotImplementedError("phase 4: TODO mobile fetch_account_diagnostics")

    # ── Реально в Phase 0 ─────────────────────────────────────────────────────

    def fetch_counters(self) -> dict:
        """GET /me?with_user_statuses=true — единственный реальный метод
        skeleton'а (smoke-test что абстракция работает). Возвращает {} если
        нет токена, произошла сетевая ошибка или не удалось разобрать JSON
        (конвенция app/oauth.py).

        HTTP ходит через библиотеку `requests` (не curl_cffi-обёртку HH),
        чтобы тесты могли mock'ать его через `responses`.
        """
        token = oauth._obtain_oauth_token(self.acc)
        if not token:
            return {}
        try:
            r = requests.get(
                "https://api.hh.ru/me",
                params={"with_user_statuses": "true"},
                headers={
                    # Тот же UA, что app/oauth.py использует для api.hh.ru
                    # (см. oauth._oauth_headers).
                    "User-Agent": "hh-clicker/1.0",
                    "Authorization": f"Bearer {token}",
                },
                timeout=15,
            )
            if r.status_code != 200:
                return {}
            return r.json()
        except (requests.RequestException, ValueError):
            # ValueError покрывает ошибку парсинга JSON из r.json().
            return {}

    # ── OAuth-extras: уже реализованы в app/oauth.py (Bearer api.hh.ru),
    #    одинаково для web и mobile — просто делегируем. ──────────────────────

    def fetch_saved_vacancy_searches(self) -> list:
        """Сохранённые поиски вакансий → oauth.fetch_saved_vacancy_searches."""
        return oauth.fetch_saved_vacancy_searches(self.acc)

    def fetch_favorited_vacancies(self) -> list:
        """Избранные вакансии → oauth.fetch_favorited_vacancies."""
        return oauth.fetch_favorited_vacancies(self.acc)

    def fetch_blacklisted_vacancies(self) -> set:
        """Вакансии в чёрном списке → oauth.fetch_blacklisted_vacancies."""
        return oauth.fetch_blacklisted_vacancies(self.acc)

    def fetch_vacancy_details(self, vid: str) -> dict:
        """Детали вакансии через OAuth → oauth.fetch_vacancy_details."""
        return oauth.fetch_vacancy_details(self.acc, vid)

    def fetch_negotiations_today_count(self) -> dict:
        """Число сегодняшних откликов → oauth.fetch_negotiations_today_count."""
        return oauth.fetch_negotiations_today_count(self.acc)

    def fetch_negotiations_statistic(self) -> dict:
        """Streak-статистика откликов → oauth.fetch_negotiations_statistic."""
        return oauth.fetch_negotiations_statistic(self.acc)

    def fetch_resume_status(self) -> dict:
        """Статус резюме → oauth.fetch_resume_status."""
        return oauth.fetch_resume_status(self.acc)

    def fetch_employer_rating_oauth(self, employer_id: str) -> dict:
        """Рейтинг работодателя через OAuth → oauth.fetch_employer_rating
        (имя с `_oauth`, чтобы не сталкиваться с web-методом fetch_employer_rating)."""
        return oauth.fetch_employer_rating(self.acc, employer_id)
