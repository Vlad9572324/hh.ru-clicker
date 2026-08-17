"""Capability-слои HHClient (fix P2): HHClientBase / WebOnlyOps / MobileOnlyOps.

Проверяют, что:
- абстрактный набор HHClient == объединению capability-слоёв (и в точности
  равен ожидаемым группам методов — защита от случайной потери метода);
- конкретные клиенты инстанцируются и не имеют абстрактных методов;
- isinstance-проверки по capability-слоям соответствуют выбранным базам;
- web-клиент не имеет аналога GET /me, а fill_questionnaire присутствует
  у обоих (решение Phase 3: mobile делегирует в web-flow — нативного
  endpoint'а анкет в APK нет, официальное приложение открывает web-анкету
  в webview).
"""
import asyncio
import concurrent.futures

import pytest

from app import hh_apply
from app.hh_client import HHClient, HHClientBase, MobileOnlyOps, WebOnlyOps
from app.hh_client_mobile import MobileHHClient
from app.hh_client_web import WebHHClient


def _run_coro(coro):
    # pytest-playwright (tests/e2e/) держит asyncio-loop «running» в главном
    # потоке до конца сессии, поэтому прямой asyncio.run() падает с
    # RuntimeError. Запускаем корутину в отдельном потоке — там лупа нет.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()

# ---------------------------------------------------------------------------
# Ожидаемые множества абстрактных методов по группам. Перечислены явно, чтобы
# будущий рефакторинг не мог незаметно потерять или задвоить метод.
# ---------------------------------------------------------------------------

# Группа A — переговоры / чат (общий слой)
GROUP_A_NEGOTIATIONS_CHAT = {
    "fetch_negotiations",
    "fetch_thread",
    "send_message",
    "send_workflow_event",
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
}

# Группа B — отклики БЕЗ fill_questionnaire (она web-only, живёт в WebOnlyOps)
GROUP_B_APPLY_COMMON = {
    "submit_response",
    "check_vacancy_before_apply",
    "check_limit",
    "touch_resume",
    "fetch_related_vacancies",
}

# Группа C — резюме (общий слой)
GROUP_C_RESUME = {
    "fetch_stats",
    "fetch_resume",
    "fetch_resume_view_history",
    "fetch_resume_views_aggregate",
    "analyze_resume",
    "edit_resume_field",
    "set_job_search_status",
    "fetch_account_diagnostics",
}

# Группа E — OAuth-extras (общий слой, включая fetch_employer_rating_oauth)
GROUP_E_OAUTH_EXTRAS = {
    "fetch_saved_vacancy_searches",
    "fetch_favorited_vacancies",
    "fetch_blacklisted_vacancies",
    "fetch_vacancy_details",
    "fetch_negotiations_today_count",
    "fetch_negotiations_statistic",
    "fetch_resume_status",
    "fetch_employer_rating_oauth",
}

GROUP_F_SEARCH = {"search_vacancies"}

WEB_ONLY = {"fill_questionnaire"}
MOBILE_ONLY = {"fetch_counters"}

EXPECTED_BASE = (
    GROUP_A_NEGOTIATIONS_CHAT | GROUP_B_APPLY_COMMON | GROUP_C_RESUME | GROUP_E_OAUTH_EXTRAS
    | GROUP_F_SEARCH
)
EXPECTED_FULL = EXPECTED_BASE | WEB_ONLY | MOBILE_ONLY

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}


def test_groups_are_disjoint_and_total_39():
    groups = [
        GROUP_A_NEGOTIATIONS_CHAT,
        GROUP_B_APPLY_COMMON,
        GROUP_C_RESUME,
        GROUP_E_OAUTH_EXTRAS,
        WEB_ONLY,
        MOBILE_ONLY,
        GROUP_F_SEARCH,
    ]
    flat = [name for g in groups for name in g]
    assert len(flat) == len(set(flat)) == 39


def test_base_layer_has_exactly_common_methods():
    assert set(HHClientBase.__abstractmethods__) == EXPECTED_BASE
    # Ради этого и затеян split: несовместимые capabilities НЕ в общем слое,
    # иначе тип HHClientBase снова не гарантировал бы вызываемость.
    assert "fill_questionnaire" not in HHClientBase.__abstractmethods__
    assert "fetch_counters" not in HHClientBase.__abstractmethods__


def test_capability_layers_exact():
    assert set(WebOnlyOps.__abstractmethods__) == WEB_ONLY
    assert set(MobileOnlyOps.__abstractmethods__) == MOBILE_ONLY


def test_hh_client_is_union_of_capability_layers():
    assert set(HHClient.__abstractmethods__) == EXPECTED_FULL
    assert set(HHClient.__abstractmethods__) == (
        set(HHClientBase.__abstractmethods__)
        | set(WebOnlyOps.__abstractmethods__)
        | set(MobileOnlyOps.__abstractmethods__)
    )


@pytest.mark.parametrize("cls", [WebHHClient, MobileHHClient])
def test_concrete_clients_instantiate_and_have_no_abstract_methods(cls):
    client = cls(ACC)
    assert client.acc is ACC
    assert cls.__abstractmethods__ == frozenset()


@pytest.mark.parametrize("cls", [WebHHClient, MobileHHClient])
def test_concrete_clients_satisfy_every_capability_layer(cls):
    # Выбранная база конкретных классов не сужалась (полная backward-compat):
    # обе реализации наследуют полный контракт HHClient и определяют ВСЕ его
    # методы (заглушки NotImplementedError тоже считаются — capability
    # о наличии метода, платформенная семантика — TBD).
    client = cls(ACC)
    assert isinstance(client, HHClientBase)
    assert isinstance(client, WebOnlyOps)
    assert isinstance(client, MobileOnlyOps)
    assert isinstance(client, HHClient)


def test_web_client_fetch_counters_not_implemented():
    with pytest.raises(NotImplementedError, match="не имеет аналога"):
        WebHHClient(ACC).fetch_counters()


def test_fill_questionnaire_present_on_both_clients(monkeypatch):
    web = WebHHClient(ACC)
    mobile = MobileHHClient(ACC)
    assert callable(web.fill_questionnaire)
    assert callable(mobile.fill_questionnaire)
    # Решение Phase 3: mobile делегирует в web-flow hh_apply (в APK нет
    # нативного endpoint'а анкет — официальное приложение открывает
    # web-анкету в webview), NotImplementedError больше не кидается.
    sentinel = ("sent", {})
    calls = []

    async def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(hh_apply, "fill_and_submit_questionnaire", fake)

    result = _run_coro(mobile.fill_questionnaire("v1", "T", "C"))

    assert result is sentinel
    assert len(calls) == 1
    fwd_args, fwd_kwargs = calls[0]
    assert fwd_args == (ACC, "v1", "T", "C")
    assert fwd_args[0] is ACC  # тот же объект, не копия
    assert fwd_kwargs == {}
