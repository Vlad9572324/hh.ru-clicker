"""
FallbackHHClient — auto-fallback обёртка mobile → web (Phase 2).

Фабрика (app/hh_client_factory.py) при mode="mobile" возвращает эту обёртку
вместо голого MobileHHClient: каждый вызов сначала идёт в mobile-клиент
(OAuth Bearer api.hh.ru), а если mobile падает со «fallback-статусом» —
0 (сеть), 401 (нет/протух токен), 403 (нет scope), 5xx (сервер лежит),
см. app.hh_mobile_transport.is_fallback_status — вызов прозрачно
повторяется через web-клиент (cookies hh.ru) с теми же аргументами.

Правила делегирования (одинаковы для КАЖДОГО метода полного контракта
HHClient, включая async submit_response/fill_questionnaire):
- mobile вернул значение → возвращаем его, web НЕ вызывается;
- MobileAPIError со fallback-статусом → log_debug + вызов web;
- MobileAPIError с прочим статусом (400/404/409/...) → перекидываем как есть;
- NotImplementedError из mobile (метод там не реализован, заглушка
  "phase N: TODO") → сразу вызов web (например, fill_questionnaire —
  web-only); если web тоже кидает NotImplementedError (web-аналога нет
  вовсе, например fetch_counters), он перекидывается наружу;
- прочие исключения → перекидываем без преобразования.

Обёртка реализует полный контракт HHClient (HHClientBase + WebOnlyOps +
MobileOnlyOps): делегаты генерируются по явному списку имён _METHODS
(синхронизирован с HHClient — guard-assert при импорте), поэтому экземпляры
проходят isinstance по HHClient и всем capability-слоям, а hasattr/getattr
видят каждый метод как обычный атрибут класса.
"""

import inspect

from app.hh_client import HHClient
from app.hh_mobile_transport import MobileAPIError, is_fallback_status
from app.logging_utils import log_debug
from app.mobile_job_search_status import normalize_job_search_status

# Явный список делегируемых методов: полный контракт HHClient =
# группа A (переговоры/чат) + группа B (отклики) + группа C (резюме) +
# группа E (OAuth-extras) — всё в HHClientBase, плюс
# WebOnlyOps.fill_questionnaire и MobileOnlyOps.fetch_counters.
# При добавлении метода в HHClient добавьте имя сюда (guard ниже уронит
# импорт при рассинхроне).
_METHODS = (
    "search_vacancies",
    # ── Группа A — переговоры / чат ──────────────────────────────────────
    "fetch_negotiations",
    "fetch_thread",
    "send_message",
    "fetch_chat_list",
    "fetch_chat_history",
    "fetch_quick_replies",
    "send_participant_action",
    "mark_chat_read",
    "fetch_possible_offers",
    "auto_decline_discards",
    "fetch_negotiations_metadata",
    "fetch_employer_rating",
    "fetch_employer_id_for_vacancy",
    "fetch_vacancy_owner_hr_hhid",
    # ── Группа B — отклики ───────────────────────────────────────────────
    "submit_response",
    "check_vacancy_before_apply",
    "check_limit",
    "touch_resume",
    "fetch_related_vacancies",
    # ── WebOnlyOps ───────────────────────────────────────────────────────
    "fill_questionnaire",
    # ── Группа C — резюме ────────────────────────────────────────────────
    "fetch_stats",
    "fetch_resume",
    "fetch_resume_view_history",
    "fetch_resume_views_aggregate",
    "analyze_resume",
    "edit_resume_field",
    "set_job_search_status",
    "fetch_account_diagnostics",
    # ── Группа E — OAuth-extras ──────────────────────────────────────────
    "fetch_saved_vacancy_searches",
    "fetch_favorited_vacancies",
    "fetch_blacklisted_vacancies",
    "fetch_vacancy_details",
    "fetch_negotiations_today_count",
    "fetch_negotiations_statistic",
    "fetch_resume_status",
    "fetch_employer_rating_oauth",
    # ── MobileOnlyOps ────────────────────────────────────────────────────
    "fetch_counters",
)

assert set(_METHODS) == set(HHClient.__abstractmethods__), (
    "FallbackHHClient._METHODS разошёлся с контрактом HHClient: "
    f"лишние={set(_METHODS) - set(HHClient.__abstractmethods__)}, "
    f"потеряны={set(HHClient.__abstractmethods__) - set(_METHODS)}"
)


def _make_sync_delegate(name: str):
    def delegate(self, *args, **kwargs):
        if name == "set_job_search_status" and args:
            args = (normalize_job_search_status(args[0]), *args[1:])
        try:
            return getattr(self.mobile, name)(*args, **kwargs)
        except NotImplementedError:
            # mobile-метод не реализован (заглушка "phase N: TODO") → сразу
            # web. NotImplementedError из web (метода нет и там) перекинется.
            return getattr(self.web, name)(*args, **kwargs)
        except MobileAPIError as e:
            if not is_fallback_status(e.status_code):
                raise
            log_debug(
                f"FallbackHHClient.{name}: mobile HTTP {e.status_code} — "
                f"повторяю через web-flow"
            )
            return getattr(self.web, name)(*args, **kwargs)

    delegate.__name__ = name
    delegate.__qualname__ = f"FallbackHHClient.{name}"
    return delegate


def _make_async_delegate(name: str):
    async def delegate(self, *args, **kwargs):
        try:
            return await getattr(self.mobile, name)(*args, **kwargs)
        except NotImplementedError:
            return await getattr(self.web, name)(*args, **kwargs)
        except MobileAPIError as e:
            if not is_fallback_status(e.status_code):
                raise
            log_debug(
                f"FallbackHHClient.{name}: mobile HTTP {e.status_code} — "
                f"повторяю через web-flow"
            )
            return await getattr(self.web, name)(*args, **kwargs)

    delegate.__name__ = name
    delegate.__qualname__ = f"FallbackHHClient.{name}"
    return delegate


class FallbackHHClient(HHClient):
    """Mobile-first клиент с auto-fallback на web-flow (Phase 2).

    Конструируется из двух готовых клиентов: mobile (основной транспорт)
    и web (fallback); acc берётся от mobile. Атрибуты:
    - .mode == "mobile" — наблюдаемость (основной транспорт — mobile,
      web используется только для fallback);
    - .mobile / .web — обёрнутые клиенты.
    """

    def __init__(self, mobile, web):
        super().__init__(mobile.acc)
        self.mobile = mobile
        self.web = web
        self.mode = "mobile"


# Генерация делегатов: каждый метод полного контракта становится реальным
# атрибутом класса (isinstance/hasattr/dir видят их как обычные методы).
# async-методы (submit_response, fill_questionnaire) определяются по ABC —
# abstractmethod не прячет coroutine-природу функции.
for _name in _METHODS:
    if inspect.iscoroutinefunction(getattr(HHClient, _name)):
        setattr(FallbackHHClient, _name, _make_async_delegate(_name))
    else:
        setattr(FallbackHHClient, _name, _make_sync_delegate(_name))

# Делегаты добавлены setattr'ом ПОСЛЕ создания класса, а ABCMeta вычисляет
# __abstractmethods__ один раз при class-creation — пересчитываем вручную.
# Все методы контракта реально определены (guard-assert выше + тесты
# tests/test_hh_client_fallback.py на полноту), поэтому множество пусто.
FallbackHHClient.__abstractmethods__ = frozenset()
