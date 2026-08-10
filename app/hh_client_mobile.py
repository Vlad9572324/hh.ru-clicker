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

Заглушки NotImplementedError:
  - phase 2: auto_decline_discards (decline существует только в web-flow);
  - phase 3: отклики и vacancy-метаданные,
  - phase 4: резюме/статистика.
"""

import asyncio

import requests

from app import (
    mobile_apply,
    mobile_chat_actions,
    mobile_chat_list,
    mobile_chat_thread,
    mobile_check_limit,
    mobile_neg_meta,
    mobile_negotiations,
    mobile_precheck,
    mobile_questionnaire,
    mobile_related,
    mobile_send_message,
    mobile_touch_resume,
    oauth,
)
from app.hh_client import HHClient
from app.llm import _randomize_text


class MobileHHClient(HHClient):
    """Mobile-flow реализация полного контракта HHClient (HHClientBase +
    WebOnlyOps + MobileOnlyOps): api.hh.ru через OAuth Bearer. Реально:
    fetch_counters (MobileOnlyOps), OAuth-extras и группа A без
    auto_decline_discards (Phase 2, делегирование в app/mobile_*.py);
    остальное — NotImplementedError-заглушки."""

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
        """Отклик на вакансию: POST api.hh.ru/negotiations form-urlencoded
        (vacancy_id, resume_id, with_chat_info=true, [message]; tracking
        query hhtmSource/hhtmFrom — контракт APK NegotiationApi).

        letter: шаблон acc["letter"] через _randomize_text (как web
        send_response_async); letter_max_length — hard-cap, обрезаем чтобы
        HH не отказал 400. Вызов мобильной функции — синхронный requests
        внутри, поэтому крутим в executor'е чтобы не блокировать loop.

        Бизнес-ошибки (не-2xx, не fallback) маппятся в web-совместимый
        tuple как classify_apply_response: ok → ("sent",
        {"negotiation_id"}); limit_exceeded → ("limit", info);
        test_required → ("test", info); already_applied → ("already",
        info); прочее → ("error", info). info всегда содержит error_type
        и http_status. Fallback-статусы (0/401/403/5xx) — MobileAPIError
        поднимается наверх без обработки (FallbackHHClient повторит через
        web-flow)."""
        letter = ""
        if self.acc.get("letter", ""):
            letter = _randomize_text(self.acc.get("letter", ""))
        if letter_max_length and len(letter) > letter_max_length:
            letter = letter[:letter_max_length].rstrip()
        resume_id = self.acc.get("resume_hash", "")
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: mobile_apply.submit_response(
                self.acc, vid, resume_id=resume_id, message=letter),
        )
        if result.get("ok"):
            return "sent", {"negotiation_id": result.get("negotiation_id", "")}
        info = {
            "error_type": result.get("error_type", ""),
            "http_status": result.get("http_status"),
        }
        error_type = info["error_type"]
        if error_type == "limit_exceeded":
            return "limit", info
        if error_type == "test_required":
            return "test", info
        if error_type == "already_applied":
            return "already", info
        return "error", info

    async def fill_questionnaire(self, vid: str, vacancy_title: str = "", company: str = "") -> tuple:
        """Заполнение анкеты при отклике (Phase 3: делегирование в web-flow).

        Решение Phase 3 (разбор APK ru.hh.android v26.28.1): нативного
        mobile-endpoint'а для анкет НЕТ — официальное приложение при
        error_type=test_required показывает alert и открывает WEB-страницу
        анкеты (applicant/vacancy_response) в webview. Поэтому mobile-клиент
        делегирует в web-flow: app/mobile_questionnaire.py →
        hh_apply.fill_and_submit_questionnaire (cookies hh.ru в acc те же).
        """
        return await mobile_questionnaire.fill_questionnaire(
            self.acc, vid, vacancy_title, company)

    def check_vacancy_before_apply(self, vid: str) -> dict:
        """Пре-проверка вакансии перед откликом: GET
        api.hh.ru/resume_profile/data_inconsistency?vacancy_id&resume_id&
        flow=vacancy_response&auto_seen=true — каких элементов резюме не
        хватает для отклика (пустой список = всё в порядке). Fail-closed:
        пустое тело → reason=empty_response, прочие не-fallback не-2xx →
        reason=http_<status> (лучше пропустить вакансию, чем тратить лимит);
        fallback-статусы (0/401/403/5xx) — MobileAPIError наверх для
        повтора через web-flow."""
        return mobile_precheck.check_vacancy_before_apply(
            self.acc, vid, resume_id=self.acc.get("resume_hash", ""))

    def check_limit(self) -> bool:
        """Дневной лимит откликов: мобильная эвристика по
        GET api.hh.ru/negotiations_statistic/mine (streak-статистика
        applicant_statistic.responses_streak.{responses_count,
        responses_required}). True = лимит активен (can_apply False) —
        семантика web hh_apply.check_limit. MobileAPIError на
        fallback-статусах (0/401/403/5xx) поднимается наверх —
        FallbackHHClient прозрачно повторит проверку через web
        check_limit."""
        data = mobile_check_limit.check_limit(self.acc)
        return not data.get("can_apply", True)

    def touch_resume(self) -> tuple:
        """Поднять резюме в поиске: POST
        api.hh.ru/resumes/{resume_id}/publish?with_professional_roles=true
        (контракт APK, тела нет; 429 → паритетное с web сообщение о кулдауне).
        Прочие 4xx → NotImplementedError — FallbackHHClient прозрачно
        повторит через web hh_apply.touch_resume."""
        return mobile_touch_resume.touch_resume(
            self.acc, self.acc.get("resume_hash", ""))

    def fetch_related_vacancies(self, seed_vid: str, max_pages: int = 1) -> list:
        """Похожие вакансии для расширения пула: GET
        api.hh.ru/vacancies/possible_job_offers → уникальные vacancy_id
        (строки). Отличие от web /shards/vacancy/related_vacancies: в
        mobile-API нет seed-based ранжирования — источник не персонализирован
        под seed. max_pages игнорируется (у эндпоинта нет пагинации).
        GET /vacancies/{seed}/suitable_resumes — только диагностика
        (возвращает резюме, не вакансии)."""
        return mobile_related.fetch_related_vacancies(self.acc, seed_vid, max_pages)

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
