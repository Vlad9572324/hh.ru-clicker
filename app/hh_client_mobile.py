"""
MobileHHClient — mobile-клиент hh.ru (api.hh.ru, OAuth Bearer).

Реализовано:
  - fetch_counters() — smoke-test абстракции (GET /me?with_user_statuses=true);
  - oauth-extras (группа E) — эти вызовы уже живут в app/oauth.py и работают
    через Bearer одинаково для web и mobile, поэтому просто делегируем туда;
  - Phase 2 (переговоры/чаты) — реальные вызовы api.hh.ru через общий
    транспорт app/hh_mobile_transport.py (модули app/mobile_*.py):
    fetch_negotiations, fetch_thread, fetch_chat_history, send_message,
    fetch_chat_list, fetch_quick_replies, send_participant_action,
    mark_chat_read, fetch_possible_offers, fetch_negotiations_metadata.
    Политика ошибок: fallback-статусы (0/401/403/5xx) поднимаются
    MobileAPIError — фабрика оборачивает клиент в FallbackHHClient,
    который прозрачно повторяет такие вызовы через web-flow; прочие
    статусы обработаны в модулях (дефолты/sentinel'ы как в web).

  - Phase 4 (резюме/статистика) — реальные вызовы api.hh.ru через тот же
    транспорт (модули app/mobile_resume*.py + app/mobile_job_search_status.py):
    fetch_resume, fetch_stats, fetch_resume_view_history,
    fetch_resume_views_aggregate, analyze_resume, edit_resume_field,
    set_job_search_status. Политика ошибок та же: fallback-статусы
    (0/401/403/5xx) поднимаются MobileAPIError → авто-повтор через web.
    Расхождения форматов с web (fetch_resume: dict вместо str;
    fetch_resume_view_history: dict {items, total} вместо list)
    задокументированы в модулях и отчёте Phase 4.

Заглушки NotImplementedError:
  - phase 2: auto_decline_discards (decline существует только в web-flow);
  - phase 3: отклики и vacancy-метаданные,
  - phase 4: fetch_account_diagnostics (составной SSR-метод, web fallback).
"""

import requests

from app import (
    mobile_chat_actions,
    mobile_chat_list,
    mobile_chat_thread,
    mobile_job_search_status,
    mobile_neg_meta,
    mobile_negotiations,
    mobile_resume,
    mobile_resume_aggregate,
    mobile_resume_analyze,
    mobile_resume_edit,
    mobile_resume_stats,
    mobile_resume_views,
    mobile_send_message,
    oauth,
)
from app.hh_client import HHClient


class MobileHHClient(HHClient):
    """Mobile-flow реализация полного контракта HHClient (HHClientBase +
    WebOnlyOps + MobileOnlyOps): api.hh.ru через OAuth Bearer. Реально:
    fetch_counters (MobileOnlyOps), OAuth-extras, группа A без
    auto_decline_discards (Phase 2) и группа C без fetch_account_diagnostics
    (Phase 4, делегирование в app/mobile_*.py); остальное —
    NotImplementedError-заглушки."""

    def __init__(self, acc: dict):
        super().__init__(acc)

    # ── Phase 2: переговоры/чаты (реализовано: api.hh.ru, Bearer) ─────────────
    # Делегирование в app/mobile_*.py; транспорт — app/hh_mobile_transport.py
    # (requests + responses-mock'и в тестах, конвенция fetch_counters).

    def fetch_negotiations(self, max_pages: int = 20) -> dict:
        """Список переговоров + статистика: GET api.hh.ru/negotiations
        (пагинация до конца). Совместим по ключам с web
        hh_negotiations.fetch_hh_negotiations_stats."""
        return mobile_negotiations.fetch_negotiations(self.acc, max_pages)

    def fetch_thread(self, neg_id: str) -> dict:
        """Тред переговоров (chat_id == neg_id):
        GET api.hh.ru/chats/{neg_id}?limit=50&order=next."""
        return mobile_chat_thread.fetch_thread(self.acc, neg_id)

    def send_message(self, neg_id: str, text: str, topic_id: str = "") -> bool | str:
        """Отправка сообщения: POST api.hh.ru/chats/{neg_id}/messages
        {text, idempotency_key(uuid4)}. topic_id в mobile-flow не нужен
        (один чат = один топик), сохранён в сигнатуре ради контракта."""
        return mobile_send_message.send_message(self.acc, neg_id, text)

    def fetch_chat_list(self, max_pages: int = 5) -> tuple:
        """Список чатов: GET api.hh.ru/chats (page/per_page<=20). Возврат
        совместим с web hh_chat._fetch_chat_list:
        (items_by_id, display_info, current_participant_id)."""
        return mobile_chat_list.fetch_chat_list(self.acc, max_pages)

    def fetch_chat_history(self, chat_id: str, max_messages: int = 20) -> list:
        """История сообщений чата:
        GET api.hh.ru/chats/{chat_id}?limit&order=next (текст в
        body.text.content)."""
        return mobile_chat_thread.fetch_chat_history(self.acc, chat_id, max_messages)

    def fetch_quick_replies(self, chat_id: str, msg_id: str) -> list:
        """Быстрые ответы HH: PUT
        api.hh.ru/chats/{chat_id}/suggestions/quick_replies?message_id=...
        (глагол PUT по контракту APK; GET на пути -> 405)."""
        return mobile_chat_actions.fetch_quick_replies(self.acc, chat_id, msg_id)

    def send_participant_action(self, chat_id: str, action_type: str = "TYPING") -> bool:
        """Typing-индикатор: PUT api.hh.ru/chats/{chat_id}/participants/action
        {action_type: "typing"|"none"} (контракт APK, нормализация регистра
        в модуле)."""
        return mobile_chat_actions.send_participant_action(self.acc, chat_id, action_type)

    def mark_chat_read(self, chat_id: str, message_id: str) -> bool:
        """Read-receipt «прочитано до...»: PUT
        api.hh.ru/chats/{chat_id}/messages/last_viewed_id
        (form-urlencoded message_id=<long>)."""
        return mobile_chat_actions.mark_chat_read(self.acc, chat_id, message_id)

    def fetch_possible_offers(self) -> list:
        """Возможные офферы: GET api.hh.ru/vacancies/possible_job_offers."""
        return mobile_neg_meta.fetch_possible_offers(self.acc)

    def auto_decline_discards(self) -> int:
        """Автоотклонение DISCARD-переговоров. Mobile-эндпоинта нет —
        decline существует только в web-flow (/applicant/negotiations/decline);
        FallbackHHClient прозрачно повторит через web-flow."""
        raise NotImplementedError("phase 2: TODO mobile auto_decline_discards")

    def fetch_negotiations_metadata(self) -> dict:
        """Метаданные переговоров: GET api.hh.ru/negotiations ->
        topics_by_vid (per-vacancy статусы). politeness/activity доступны
        только в web-SSR — в mobile пусты."""
        return mobile_neg_meta.fetch_negotiations_metadata(self.acc)

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

    # ── Phase 4: резюме/статистика (реализовано: api.hh.ru, Bearer) ──────────
    # Делегирование в app/mobile_resume*.py и app/mobile_job_search_status.py;
    # транспорт — app/hh_mobile_transport.py, резолв hash'а резюме —
    # app/mobile_resume_common.py (контракты: scratchpad/apidocs
    # apidocs_group_2/3/5.yaml + apk_writes_group_5.yaml).

    def fetch_resume(self, resume_id: str | None = None) -> dict:
        """Полное резюме JSON: GET api.hh.ru/resumes/{id}
        (?with_professional_roles=true&with_creds=true). resume_id=None —
        первое резюме аккаунта (mobile_resume_common.resolve_resume_id).
        ВНИМАНИЕ: mobile возвращает dict (полный JSON резюме), web — str
        (текст для LLM); расхождение задокументировано в отчёте Phase 4."""
        return mobile_resume.fetch_resume(self.acc, resume_id)

    def fetch_stats(self, resume_id: str | None = None) -> dict:
        """Статистика резюме: GET /me?with_user_statuses=true (counters:
        new_resume_views/unread_negotiations/resumes_count) +
        GET /resumes/{id} (total_views/new_views) +
        GET /negotiations_statistic/mine (streak). Ключи совместимы с web
        hh_resume.fetch_resume_stats; shows/invitations в mobile недоступны
        (web-SSR данные) — нули."""
        return mobile_resume_stats.fetch_stats(self.acc, resume_id)

    def fetch_resume_view_history(self, limit: int = 50, resume_id: str | None = None) -> dict:
        """Кто смотрел резюме: GET api.hh.ru/resumes/{id}/views (пагинация
        до limit). Возврат {items: [{employer_id, name, viewed_at, viewed}],
        total}. ВНИМАНИЕ: mobile возвращает dict с флагом viewed, web —
        list; расхождение задокументировано в отчёте Phase 4."""
        return mobile_resume_views.fetch_resume_view_history(self.acc, resume_id, limit)

    def fetch_resume_views_aggregate(self, resume_id: str | None = None) -> dict:
        """Агрегация просмотров: GET /resumes/{id}/views (все страницы) →
        {total, new (viewed=false), by_employer_top10} + web-алиасы
        total_all_time/total_new (graph_30d в mobile пуст)."""
        return mobile_resume_aggregate.fetch_resume_views_aggregate(self.acc, resume_id)

    def analyze_resume(self, extra_terms: list = None, resume_id: str | None = None) -> dict:
        """ML-аудит резюме: комбинация GET /resumes/{id} +
        POST /skills_profile/predictions/recommended_skills/resume +
        POST /skills_profile/suggestions/duties +
        POST /skills_profile/predictions/subroles/by_title +
        GET /career_platform/profile?profession_description=true. Возврат
        {ok, missing_skills, recommended_duties, subroles, grade,
        current_score}. extra_terms в mobile не используется (web-SSR
        supply/demand), сохранён в сигнатуре ради контракта."""
        return mobile_resume_analyze.analyze_resume(self.acc, resume_id)

    def edit_resume_field(self, resume_hash: str, fields: dict) -> dict:
        """Редактирование полей резюме: валидация по
        GET /resumes/{id}/conditions (regexp/длины) +
        PUT /resume_profile/{id} с JSON-diff
        {resume: fields, creds: {}, additional_properties: {}}
        (контракт APK EditResumeProfileRequestNetwork). Возврат
        {ok, error?, updated_field?}."""
        return mobile_resume_edit.edit_resume_field(self.acc, resume_hash, fields)

    def set_job_search_status(self, status: str) -> dict:
        """Смена статуса поиска работы: PUT
        /user_statuses/job_search_statuses/mine (form id=<status>, контракт
        APK JobSearchStatusRemoteApi). Возврат {ok, status, label} либо
        {ok: False, error}."""
        return mobile_job_search_status.set_job_search_status(self.acc, status)

    def fetch_account_diagnostics(self) -> dict:
        """Диагностика аккаунта (phase 4). Составной web-SSR метод
        (/applicant/resumes) — mobile-аналога нет; FallbackHHClient
        прозрачно повторит через web-flow."""
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
