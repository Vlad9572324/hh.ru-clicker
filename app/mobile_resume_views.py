"""Mobile-версия fetch_resume_view_history: кто смотрел резюме (Phase 4).

Источник: GET https://api.hh.ru/resumes/{resume_id}/views — лента
просмотров резюме: items[{created_at, viewed: bool, employer{id, name,
url, alternate_url, logo_urls, vacancies_url}}], found, pages, page,
per_page (scratchpad/apidocs/apidocs_group_2.yaml, live 2026-08-10).
Флаг viewed=false — новый (не просмотренный соискателем) просмотр.

Возврат (контракт Phase 4):
    {"items": [{"employer_id", "name", "viewed_at", "viewed"}, ...],
     "total": <found>}

Транспорт — app.hh_mobile_transport.mobile_request. Политика ошибок:
fallback-статусы (0/401/403/5xx) — MobileAPIError наверх (повтор через
web-flow); прочие не-2xx (404 и т.п.) — {"items": [], "total": 0}.

ВНИМАНИЕ (расхождение с web, задокументировано в отчёте Phase 4):
web-версия hh_resume.fetch_resume_view_history возвращает list
[{employer_id, name, date, vacancy}] из SSR; mobile-версия возвращает
dict {items, total} с флагом viewed (данные API богаче: точный timestamp
и признак нового просмотра).
"""

from app.hh_mobile_transport import (
    MOBILE_BASE,
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug
from app.mobile_resume_common import resolve_resume_id

# Защитный потолок пагинации: не более 10 страниц за один вызов —
# гарантия от бесконечного цикла при битом pages/found со стороны сервера.
_MAX_PAGES = 10


def _map_view_item(item: dict) -> dict:
    """Один элемент ленты просмотров → форма контракта Phase 4:
    employer_id/name (пустое имя → "Аноним"), viewed_at — строка
    created_at как есть (без парсинга), viewed — флаг просмотренности
    соискателем (False = новый просмотр)."""
    employer = item.get("employer")
    if not isinstance(employer, dict):
        employer = {}
    name = str(employer.get("name") or "").strip()
    return {
        "employer_id": str(employer.get("id") or ""),
        "name": name or "Аноним",
        "viewed_at": item.get("created_at"),
        "viewed": bool(item.get("viewed")),
    }


def fetch_resume_view_history(acc: dict, resume_id=None, limit: int = 50) -> dict:
    """История просмотров резюме через mobile-API.

    resume_id=None — резолвится в первое резюме аккаунта
    (resolve_resume_id: явный аргумент → acc["resume_hash"] → список
    резюме); если резолвить нечего — {"items": [], "total": 0} без
    запросов. limit — сколько элементов ленты вернуть: пагинация
    page=0,1,... с per_page = min(max(int(limit), 1), 100), сбор идёт
    пока len(items) < limit и страница < pages из ответа; защитный
    потолок — не более 10 страниц.

    Возвращает {"items": [{employer_id, name, viewed_at, viewed}, ...],
    "total": found} (total — found из последней страницы; если сервер не
    отдал found — число собранных элементов).

    Ошибки: fallback-статусы (0/401/403/5xx, см. is_fallback_status) —
    MobileAPIError поднимается наверх (повтор через web-flow); прочие
    не-2xx (404 и т.п.) — {"items": [], "total": 0} без исключения.
    """
    rid = resolve_resume_id(acc, resume_id)
    if not rid:
        # Резюме не найдено — запросы к /views бессмысленны.
        return {"items": [], "total": 0}

    per_page = min(max(int(limit), 1), 100)
    url = f"{MOBILE_BASE}/resumes/{rid}/views"
    items: list = []
    found = None
    pages = None

    for page in range(_MAX_PAGES):
        if len(items) >= limit:
            break
        try:
            data = mobile_request(acc, "GET", url,
                                  params={"page": page, "per_page": per_page})
        except MobileAPIError as e:
            if is_fallback_status(e.status_code):
                raise  # 0/401/403/5xx → fallback на web-flow выше по стеку
            log_debug(f"mobile fetch_resume_view_history {url} page={page}: "
                      f"HTTP {e.status_code}")
            return {"items": [], "total": 0}

        if not isinstance(data, dict):
            break
        try:
            found = int(data.get("found"))
        except (TypeError, ValueError):
            pass  # держим последний известный found
        try:
            pages = int(data.get("pages"))
        except (TypeError, ValueError):
            pages = None

        page_items = data.get("items")
        if not isinstance(page_items, list) or not page_items:
            break
        for it in page_items:
            if isinstance(it, dict):
                items.append(_map_view_item(it))

        if pages is not None and page + 1 >= pages:
            break  # сервер сообщил, что страницы закончились

    if found is None:
        found = len(items)
    return {"items": items[:limit], "total": found}
