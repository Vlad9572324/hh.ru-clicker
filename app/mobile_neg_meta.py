"""Mobile-версии метаданных переговоров и возможных офферов (Phase 2).

Два OAuth-endpoint'а api.hh.ru, заменяющие web-источники:

1. GET https://api.hh.ru/negotiations — список переговоров (topics): из
   каждого item'а достаются per-vacancy статусы (viewed_by_opponent,
   state.id, has_new_messages). Форма item'а — как у GET
   /negotiations/{topic_id} (scratchpad/apidocs/apidocs_group_1.yaml):
   {id, state{id,name}, viewed_by_opponent, has_new_messages,
   counters{messages,unread_messages}, vacancy{id,name,...}}.
2. GET https://api.hh.ru/vacancies/possible_job_offers — официальный
   OAuth-аналог web-шарда /shards/applicant/negotiations/possible_job_offers
   (web-версия: app.hh_negotiations.fetch_hh_possible_offers).

Транспорт — app.hh_mobile_transport.mobile_request (Bearer + mobile UA +
x-force-app-access). Fallback-политика: на 5xx/сеть (is_fallback_status)
MobileAPIError перекидывается наверх — fallback-обёртка повторит запрос
через web-flow.
"""

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug


def fetch_negotiations_metadata(acc: dict) -> dict:
    """Метаданные переговоров через mobile-API (аналог web
    fetch_negotiations_metadata из app.hh_negotiations).

    Возвращает dict той же структуры, что web-версия:
    {"politeness": {...}, "activity": {...}, "topics_by_vid": {...}}.

    topics_by_vid: {vacancy_id: {viewed_by_opponent, unread_by_employer,
                                 last_state, has_new_messages}}.

    politeness (per-employer % чтения и дни ответа) и activity (онлайн-
    статусы HR) в mobile-API НЕдоступны — это данные web-SSR страницы
    /applicant/negotiations (applicantEmployerPoliteness /
    applicantEmployerManagersActivity). Возвращаем пустые dict'ы, чтобы
    потребители (см. routes/accounts.py) видели ту же структуру.

    Ошибки: fallback-статусы (0/401/403/5xx, см. is_fallback_status) —
    MobileAPIError поднимается наверх: FallbackHHClient прозрачно повторяет
    запрос через web-flow (web-версия отдаст полные politeness/activity из
    SSR); прочие 4xx — возвращаем пустую структуру НЕ кидая (метаданные
    некритичны).
    """
    out: dict = {"politeness": {}, "activity": {}, "topics_by_vid": {}}
    try:
        data = mobile_request(acc, "GET", "/negotiations",
                              params={"page": 0, "per_page": 100})
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # 0 (сеть) / 401 / 403 / 5xx: не глотим — fallback-обёртка
            # повторит через web-flow.
            raise
        log_debug(f"mobile fetch_negotiations_metadata: HTTP {e.status_code} "
                  f"| {e.payload} — возвращаю пустую структуру")
        return out

    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    for it in items:
        if not isinstance(it, dict):
            continue
        vacancy = it.get("vacancy") or {}
        vid = vacancy.get("id") if isinstance(vacancy, dict) else None
        if not vid:
            continue
        state = it.get("state") or {}
        counters = it.get("counters") or {}
        out["topics_by_vid"][str(vid)] = {
            "viewed_by_opponent": bool(it.get("viewed_by_opponent")),
            # Mobile-API не отдаёт "непрочитано работодателем" (counters.
            # unread_messages — непрочитанное у соискателя) → дефолт 0.
            "unread_by_employer": int(counters.get("unread_by_employer", 0) or 0),
            "last_state": state.get("id", "") if isinstance(state, dict) else "",
            "has_new_messages": bool(it.get("has_new_messages")),
        }
    return out


def fetch_possible_offers(acc: dict) -> list:
    """Компании, готовые пригласить, через mobile-API (аналог web
    fetch_hh_possible_offers из app.hh_negotiations).

    GET https://api.hh.ru/vacancies/possible_job_offers — официальный
    OAuth-endpoint. Ответ может быть list либо dict с "items".

    Возвращает list dict'ов {"name": ..., "vacancyNames": [...]} — формат
    совместим с web-версией. Названия вакансий берутся из vacancies[].name
    либо одиночного vacancy.name.

    Ошибки: на fallback-статусах (0 сеть / 401 / 403 / 5xx) перекидывает
    MobileAPIError наверх (для повтора через web-flow); прочие не-2xx
    (404 и т.п.) — пустой список.
    """
    try:
        data = mobile_request(acc, "GET", "/vacancies/possible_job_offers")
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise
        log_debug(f"mobile fetch_possible_offers: HTTP {e.status_code} | {e.payload}")
        return []

    items = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else None)
    if not isinstance(items, list):
        items = []
    offers: list = []
    for item in items:
        if not isinstance(item, dict):
            continue
        vacancies = item.get("vacancies")
        if not isinstance(vacancies, list):
            single = item.get("vacancy")
            vacancies = [single] if isinstance(single, dict) else []
        offers.append({
            "name": item.get("name", ""),
            "vacancyNames": [v.get("name", "") for v in vacancies
                             if isinstance(v, dict)],
        })
    return offers
