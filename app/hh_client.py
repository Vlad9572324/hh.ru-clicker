"""
HHClient — абстрактный интерфейс клиента hh.ru («один клиент — один аккаунт»).

Phase 0 рефакторинга mobile-api: ТОЛЬКО абстракция, без миграции логики.
У бота два способа общения с hh.ru:
- web-flow — cookies через hh.ru + chatik.hh.ru;
- mobile-flow — OAuth Bearer через api.hh.ru.

Capability-дизайн (fix P2: один ABC смешивал несовместимые capabilities —
web-only fill_questionnaire и mobile-only fetch_counters, из-за чего тип
HHClient не гарантировал вызываемость методов):

- HHClientBase — общий слой: методы, которые обе реализации имеют (или
  planned-имеют) с одинаковой семантикой. Тип HHClientBase ГАРАНТИРУЕТ
  вызываемость всех своих методов: группа A (переговоры/чат),
  группа B (отклики, БЕЗ fill_questionnaire), группа C (резюме),
  группа E (OAuth-extras, включая fetch_employer_rating_oauth).
- WebOnlyOps — capability web-only операций: fill_questionnaire
  (анкета при отклике; в mobile-flow аналога нет).
- MobileOnlyOps — capability mobile-only операций: fetch_counters
  (GET /me; в web-flow аналога нет).
- HHClient = HHClientBase + WebOnlyOps + MobileOnlyOps — ПОЛНЫЙ контракт.
  Сохранён как объединение слоёв ради полной backward-compat: импорт
  `from app.hh_client import HHClient` и семантика «полный интерфейс»
  не меняются. Новый код, которому нужна гарантия вызываемости конкретного
  метода, должен типизироваться против HHClientBase или нужного *OnlyOps.

Реализации:
- WebHHClient (app/hh_client_web.py) — делегирует в существующие web-flow
  функции app/hh_chat.py, app/hh_apply.py, app/hh_negotiations.py,
  app/hh_resume.py и app/oauth.py. Ноль новой логики, только адаптер:
  подставляет self.acc первым аргументом в существующую функцию.
- MobileHHClient (app/hh_client_mobile.py) — mobile-flow (OAuth Bearer
  api.hh.ru); реально реализованы fetch_counters(), OAuth-extras и
  переговоры/чаты (Phase 2: делегирование в app/mobile_*.py через общий
  транспорт app/hh_mobile_transport.py). Фабрика оборачивает mobile-клиент
  в FallbackHHClient (app/hh_client_fallback.py): fallback-статусы
  (0/401/403/5xx) и NotImplementedError-заглушки прозрачно повторяются
  через WebHHClient. Заглушки остались для фаз 3/4 (+auto_decline_discards).

Выбор реализации: app/hh_client_factory.py::get_client(acc) — по полю
acc["mode"] ("web" | "mobile" | "auto"; при отсутствии берётся
CONFIG.default_client_mode). Решение Phase 0 (подтверждено в Phase 2):
"auto" → всегда web; mobile — только при явном mode="mobile" (с Phase 2 —
FallbackHHClient поверх MobileHHClient с auto-fallback на web-flow);
подробнее docs/PHASE_MATRIX.md.

ВАЖНО: НЕ путать с app.hh_http.HHClient — там класс с тем же именем, но это
низкоуровневая транспортная curl_cffi/requests-обёртка (singleton HH),
не имеющая отношения к hh-домену. Здесь — абстракция доменного клиента.
"""

from abc import ABC, abstractmethod


class HHClientBase(ABC):
    """Общий capability-слой: методы, которые обе реализации (web и mobile)
    имеют или planned-имеют с одинаковой семантикой. Тип HHClientBase
    гарантирует вызываемость всех своих методов.

    Конструктор сохраняет аккаунт; методы acc не принимают — реализации
    сами подставляют self.acc в существующие hh-функции.
    """

    def __init__(self, acc: dict):
        self.acc = acc

    @abstractmethod
    def search_vacancies(self, text: str, area_id=1, per_page: int = 20,
                         page: int = 0, filters=None) -> list:
        """Поиск вакансий; mobile: GET api.hh.ru/vacancies."""
        ...

    # ------------------------------------------------------------------
    # Группа A — переговоры / чат
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch_negotiations(self, max_pages: int = 20) -> dict:
        """Статистика откликов/переговоров; web: hh_negotiations.fetch_hh_negotiations_stats."""
        ...

    @abstractmethod
    def fetch_thread(self, neg_id: str) -> dict:
        """Тред переговоров по neg_id; web: hh_chat.fetch_negotiation_thread."""
        ...

    @abstractmethod
    def send_message(self, neg_id: str, text: str, topic_id: str = "") -> bool | str:
        """Отправка сообщения в переговоры; web: hh_chat.send_negotiation_message (может вернуть "chat_not_found")."""
        ...

    @abstractmethod
    def fetch_chat_list(self, max_pages: int = 5) -> tuple:
        """Список чатов из chatik.hh.ru; web: hh_chat._fetch_chat_list."""
        ...

    @abstractmethod
    def fetch_chat_history(self, chat_id: str, max_messages: int = 20) -> list:
        """История сообщений чата; web: hh_chat._fetch_chat_history."""
        ...

    @abstractmethod
    def fetch_quick_replies(self, chat_id: str, msg_id: str) -> list:
        """Быстрые ответы для сообщения чата; web: hh_chat.fetch_quick_replies."""
        ...

    @abstractmethod
    def send_participant_action(self, chat_id: str, action_type: str = "TYPING") -> bool:
        """Отправка действия участника (TYPING/NONE); web: hh_chat.send_participant_action."""
        ...

    @abstractmethod
    def mark_chat_read(self, chat_id: str, message_id: str) -> bool:
        """Пометить чат прочитанным до message_id; web: hh_chat.mark_chat_read."""
        ...

    @abstractmethod
    def fetch_possible_offers(self) -> list:
        """Возможные офферы (possible_job_offers); web: hh_negotiations.fetch_hh_possible_offers."""
        ...

    @abstractmethod
    def auto_decline_discards(self) -> int:
        """Автоотклонение отказов; web: hh_negotiations.auto_decline_discards."""
        ...

    @abstractmethod
    def fetch_negotiations_metadata(self) -> dict:
        """Метаданные переговоров; web: hh_negotiations.fetch_negotiations_metadata."""
        ...

    @abstractmethod
    def fetch_employer_rating(self, employer_id) -> dict | None:
        """Рейтинг работодателя (web-scraping); web: hh_negotiations.fetch_employer_rating."""
        ...

    @abstractmethod
    def fetch_employer_id_for_vacancy(self, vacancy_id) -> int | None:
        """employer_id по вакансии; web: hh_negotiations.fetch_employer_id_for_vacancy."""
        ...

    @abstractmethod
    def fetch_vacancy_owner_hr_hhid(self, vacancy_id) -> int | None:
        """HR hhid владельца вакансии; web: hh_negotiations.fetch_vacancy_owner_hr_hhid."""
        ...

    # ------------------------------------------------------------------
    # Группа B — отклики (submit_response — async, как в существующем коде).
    # fill_questionnaire — web-only, вынесена в WebOnlyOps.
    # ------------------------------------------------------------------

    @abstractmethod
    async def submit_response(self, vid: str, letter_max_length: int | None = None) -> tuple:
        """Отклик на вакансию; web: hh_apply.send_response_async (mobile: oauth._oauth_apply)."""
        ...

    @abstractmethod
    def check_vacancy_before_apply(self, vid: str) -> dict:
        """Проверка вакансии перед откликом; web: hh_apply._check_vacancy_before_apply."""
        ...

    @abstractmethod
    def check_limit(self) -> bool:
        """Проверка лимита откликов; web: hh_apply.check_limit."""
        ...

    @abstractmethod
    def touch_resume(self) -> tuple:
        """«Поднять» резюме в поиске; web: hh_apply.touch_resume (уже OAuth-first внутри)."""
        ...

    @abstractmethod
    def fetch_related_vacancies(self, seed_vid: str, max_pages: int = 1) -> list:
        """Похожие вакансии от seed-вакансии; web: hh_apply.fetch_related_vacancies."""
        ...

    # ------------------------------------------------------------------
    # Группа C — резюме
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch_stats(self) -> dict:
        """Статистика резюме; web: hh_resume.fetch_resume_stats."""
        ...

    @abstractmethod
    def fetch_resume(self) -> dict:
        """Текст резюме; web: hh_resume.fetch_resume_text."""
        ...

    @abstractmethod
    def fetch_resume_view_history(self, limit: int = 50) -> list:
        """История просмотров резюме; web: hh_resume.fetch_resume_view_history."""
        ...

    @abstractmethod
    def fetch_resume_views_aggregate(self) -> dict:
        """Агрегированные просмотры резюме; web: hh_resume.fetch_resume_views_aggregate."""
        ...

    @abstractmethod
    def analyze_resume(self, extra_terms: list = None) -> dict:
        """Анализ резюме по ключевым словам; web: hh_resume._analyze_resume."""
        ...

    @abstractmethod
    def edit_resume_field(self, resume_hash: str, fields: dict) -> dict:
        """Редактирование полей резюме; web: hh_resume._edit_resume_field."""
        ...

    @abstractmethod
    def set_job_search_status(self, status: str) -> dict:
        """Установка статуса поиска работы; web: hh_resume.set_job_search_status."""
        ...

    @abstractmethod
    def fetch_account_diagnostics(self) -> dict:
        """Диагностика аккаунта; web: hh_resume.fetch_account_diagnostics."""
        ...

    # ------------------------------------------------------------------
    # Группа E — OAuth-extras (api.hh.ru, Bearer)
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch_saved_vacancy_searches(self) -> list:
        """Сохранённые поиски вакансий; web: oauth.fetch_saved_vacancy_searches."""
        ...

    @abstractmethod
    def fetch_favorited_vacancies(self) -> list:
        """Избранные вакансии; web: oauth.fetch_favorited_vacancies."""
        ...

    @abstractmethod
    def fetch_blacklisted_vacancies(self) -> set:
        """Вакансии в чёрном списке; web: oauth.fetch_blacklisted_vacancies."""
        ...

    @abstractmethod
    def fetch_vacancy_details(self, vid: str) -> dict:
        """Детали вакансии по vid; web: oauth.fetch_vacancy_details."""
        ...

    @abstractmethod
    def fetch_negotiations_today_count(self) -> dict:
        """Число переговоров за сегодня; web: oauth.fetch_negotiations_today_count."""
        ...

    @abstractmethod
    def fetch_negotiations_statistic(self) -> dict:
        """Статистика переговоров (OAuth); web: oauth.fetch_negotiations_statistic."""
        ...

    @abstractmethod
    def fetch_resume_status(self) -> dict:
        """Статус резюме (OAuth); web: oauth.fetch_resume_status."""
        ...

    @abstractmethod
    def fetch_employer_rating_oauth(self, employer_id: str) -> dict:
        """Рейтинг работодателя через OAuth api.hh.ru; web: oauth.fetch_employer_rating."""
        ...


class WebOnlyOps(ABC):
    """Capability-слой web-only операций: есть в web-flow, нет аналога в mobile."""

    @abstractmethod
    async def fill_questionnaire(self, vid: str, vacancy_title: str = "", company: str = "") -> tuple:
        """Заполнение анкеты при отклике; web: hh_apply.fill_and_submit_questionnaire (web-only)."""
        ...


class MobileOnlyOps(ABC):
    """Capability-слой mobile-only операций: есть в mobile-flow, нет аналога в web."""

    @abstractmethod
    def fetch_counters(self) -> dict:
        """Счётчики профиля (GET /me?with_user_statuses=true); реально только в mobile-клиенте, web-аналога нет."""
        ...


class HHClient(HHClientBase, WebOnlyOps, MobileOnlyOps):
    """Полный контракт hh-клиента = HHClientBase + WebOnlyOps + MobileOnlyOps.

    Объединение capability-слоёв сохранено ради backward-compat: существующий
    код (factory, тайпхинты `-> HHClient`) продолжает видеть «полный
    интерфейс». Код, которому нужна гарантия вызываемости конкретного метода,
    должен зависеть от HHClientBase (общая семантика) или от WebOnlyOps /
    MobileOnlyOps (платформенно-специфичные операции).
    """
