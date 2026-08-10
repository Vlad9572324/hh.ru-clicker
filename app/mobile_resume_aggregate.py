"""Mobile-версия fetch_resume_views_aggregate: агрегированные просмотры
резюме (Phase 4).

Источник: GET https://api.hh.ru/resumes/{resume_id}/views — все страницы
ленты просмотров (items[{created_at, viewed, employer{...}}], found) —
scratchpad/apidocs/apidocs_group_2.yaml, live 2026-08-10.

Агрегация (контракт Phase 4):
    {"total": <found — просмотры за всё время>,
     "new": <число items c viewed=false — новые/непрочитанные>,
     "by_employer_top10": [{"employer_id", "name", "views"}, ...],
     # web-совместимые алиасы (hh_resume.fetch_resume_views_aggregate):
     "total_all_time": == total, "total_new": == new}

by_employer_top10 — топ-10 работодателей по числу просмотров (сортировка:
views desc, далее name asc). 30-дневный daily-graph (web graph_30d) в
mobile-API отсутствует — ключ graph_30d возвращается пустым списком.

Транспорт — app.hh_mobile_transport.mobile_request. Политика ошибок:
fallback-статусы (0/401/403/5xx) — MobileAPIError наверх (повтор через
web-flow); прочие не-2xx (404 и т.п.) — нулевая структура. Пагинация
ограничена защитным потолком страниц (не бесконечный цикл).
"""

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug
from app.mobile_resume_common import resolve_resume_id

_PER_PAGE = 100
# Защитный потолок пагинации: не более 10 страниц (1000 просмотров),
# чтобы бесконечный цикл был невозможен даже при битом pages у HH.
_MAX_PAGES = 10


def _zero_aggregate() -> dict:
    """Нулевая структура контракта — все ключи присутствуют."""
    return {
        "total": 0,
        "new": 0,
        "by_employer_top10": [],
        "total_all_time": 0,
        "total_new": 0,
        "graph_30d": [],  # в mobile-API 30-дневного графика нет
    }


def fetch_resume_views_aggregate(acc: dict, resume_id=None) -> dict:
    """Агрегированные просмотры резюме через mobile-API (аналог web
    hh_resume.fetch_resume_views_aggregate).

    resume_id=None — резолвится в первое резюме аккаунта. Возвращает
    {"total", "new", "by_employer_top10", "total_all_time", "total_new",
    "graph_30d": []}; на fallback-статусах кидает MobileAPIError
    (повтор через web-flow).
    """
    rid = resolve_resume_id(acc, resume_id)
    if not rid:
        log_debug("mobile fetch_resume_views_aggregate: резюме не найдено — "
                  "возвращаю нулевую структуру без запросов")
        return _zero_aggregate()

    items_all: list = []
    found = None  # total из ответа; None → считаем по собранным items
    pages = 1

    for page in range(_MAX_PAGES):
        try:
            data = mobile_request(
                acc, "GET", f"/resumes/{rid}/views",
                params={"per_page": _PER_PAGE, "page": page},
            )
        except MobileAPIError as e:
            if is_fallback_status(e.status_code):
                raise  # 0/401/403/5xx → fallback на web-flow выше по стеку
            log_debug(f"mobile fetch_resume_views_aggregate page={page}: "
                      f"HTTP {e.status_code} — возвращаю то, что собрал")
            break

        if not isinstance(data, dict):
            break
        if page == 0:
            try:
                found = int(data.get("found"))
            except (TypeError, ValueError):
                found = None
        try:
            pages = int(data.get("pages"))
        except (TypeError, ValueError):
            pages = page + 1  # поля pages нет — текущая страница последняя

        items = data.get("items")
        if not isinstance(items, list) or not items:
            break
        items_all.extend(it for it in items if isinstance(it, dict))

        if page + 1 >= pages:
            break  # дошли до последней страницы

    total = found if found is not None else len(items_all)
    new = sum(1 for it in items_all if it.get("viewed") is False)

    # Счётчик просмотров по работодателю; ключ — (id строкой, имя).
    counter: dict = {}
    for it in items_all:
        emp = it.get("employer")
        if not isinstance(emp, dict):
            emp = {}
        emp_id = str(emp.get("id") or "")
        name = str(emp.get("name") or "").strip() or "Аноним"
        key = (emp_id, name)
        counter[key] = counter.get(key, 0) + 1

    # Топ-10: views desc, при равенстве — name asc.
    top10 = [
        {"employer_id": emp_id, "name": name, "views": views}
        for (emp_id, name), views in sorted(
            counter.items(), key=lambda kv: (-kv[1], kv[0][1]))
    ][:10]

    result = _zero_aggregate()
    result["total"] = total
    result["new"] = new
    result["by_employer_top10"] = top10
    result["total_all_time"] = total  # web-совместимый алиас
    result["total_new"] = new  # web-совместимый алиас
    return result
