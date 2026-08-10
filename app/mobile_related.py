"""Похожие вакансии для расширения пула через mobile-API (Phase 3).

Web-версия (app.hh_apply.fetch_related_vacancies) ходит в рекомендательный
шард GET /shards/vacancy/related_vacancies?vacancyId=X — seed-based ML-ранкер
HH подбирает вакансии, похожие на seed. В mobile-API аналога этого шарда НЕТ,
поэтому источник кандидатов — другой OAuth-endpoint:

1. GET https://api.hh.ru/vacancies/possible_job_offers (APK
   Uq/InterfaceC4443a.java) — «компании, готовые пригласить»: ответ list
   либо dict {"items": [...]} элементов вида
   {"name": <employer>, "vacancies": [{"id": ..., "name": ...}, ...]}
   (возможны одиночные {"vacancy": {...}} и флаги already_applied — парсинг
   защитный). Источник НЕ персонализирован под seed (это главное отличие от
   web-шарда), но даёт живой пул вакансий для расширения.
2. GET https://api.hh.ru/vacancies/{vacancy_id}/suitable_resumes (APK
   zy/g.java; ответ {counters{suitable, not_published, already_applied,
   unavailable}, suitable[], already_applied[],
   resume_inconsistencies{resume_id: [...]}}) — best-effort ТОЛЬКО
   диагностика: эндпоинт возвращает РЕЗЮМЕ соискателя, а не вакансии,
   поэтому в список кандидатов ничего не добавляет. Используем его, чтобы
   предупредить, если резюме может не подходить под seed
   (counters.suitable == 0 при непустом resume_inconsistencies).

Транспорт — app.hh_mobile_transport.mobile_request (Bearer + mobile UA +
x-force-app-access). Fallback-политика: на possible_job_offers fallback-
статусы (0/401/403/5xx, см. is_fallback_status) перекидываются MobileAPIError
наверх — FallbackHHClient повторит через web-flow (там настоящий seed-based
шард); прочие не-2xx (404 и т.п.) — пустой список. Ошибки диагностического
suitable_resumes глотаются ВСЕ (включая fallback-статусы): основной источник
— offers, и fallback на необязательной диагностике не должен отбрасывать уже
собранный список кандидатов.
"""

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug


def _collect_offer_vacancy_ids(data, seed_vid: str) -> list:
    """Собирает уникальные str vacancy_id из ответа possible_job_offers.

    data — list либо dict {"items": [...]}. Элементы: {"name": <employer>,
    "vacancies": [{id, name}, ...]} либо одиночные {"vacancy": {...}}.
    Элементы и vacancy-объекты с already_applied == True пропускаются
    (откликаться на них повторно смысла нет). Идентификаторы дедупятся с
    сохранением порядка; сам seed_vid в результат не попадает.
    """
    items = data if isinstance(data, list) else (
        data.get("items") if isinstance(data, dict) else None)
    if not isinstance(items, list):
        items = []
    out: list = []
    seen: set = set()
    for item in items:
        if not isinstance(item, dict) or item.get("already_applied"):
            continue
        vacancies = item.get("vacancies")
        if not isinstance(vacancies, list):
            single = item.get("vacancy")
            vacancies = [single] if isinstance(single, dict) else []
        for v in vacancies:
            if not isinstance(v, dict) or v.get("already_applied"):
                continue
            vid = v.get("id")
            vid = str(vid) if vid is not None else ""
            if not vid or vid == seed_vid or vid in seen:
                continue
            seen.add(vid)
            out.append(vid)
    return out


def _diagnose_suitable_resumes(acc: dict, seed_vid: str) -> None:
    """Best-effort диагностика по GET /vacancies/{seed_vid}/suitable_resumes.

    Эндпоинт возвращает РЕЗЮМЕ (не вакансии) — в список кандидатов ничего
    не добавляет; используем только чтобы предупредить, если резюме может не
    подходить под seed: counters.suitable == 0 при непустом
    resume_inconsistencies.

    Любая ошибка (включая fallback-статусы 0/401/403/5xx) глотается и
    пишется в log_debug: это необязательный вызов, основной источник —
    possible_job_offers, и fallback на диагностике не должен ронять метод
    (иначе уже собранный список кандидатов был бы отброшен ради web-повтора,
    который по диагностике ничего полезного не вернёт).
    """
    try:
        data = mobile_request(acc, "GET",
                              f"/vacancies/{seed_vid}/suitable_resumes")
    except MobileAPIError as e:
        log_debug(f"mobile fetch_related_vacancies: suitable_resumes "
                  f"seed={seed_vid} HTTP {e.status_code} | {e.payload}")
        return
    if not isinstance(data, dict):
        return
    counters = data.get("counters")
    if not isinstance(counters, dict):
        counters = {}
    inconsistencies = data.get("resume_inconsistencies") or {}
    if not counters.get("suitable") and inconsistencies:
        log_debug(f"mobile fetch_related_vacancies: резюме может не подходить "
                  f"под seed {seed_vid} (counters.suitable=0, "
                  f"resume_inconsistencies непуст)")


def fetch_related_vacancies(acc: dict, vacancy_id: str, max_pages: int = 1) -> list:
    """Похожие вакансии для расширения пула через mobile-API (аналог web
    fetch_related_vacancies из app.hh_apply).

    Возвращает уникальный список vacancy_id (строки, порядок сохраняется):
    кандидаты берутся из GET /vacancies/possible_job_offers. Отличие от web
    /shards/vacancy/related_vacancies: в mobile-API нет seed-based
    ранжирования — источник не персонализирован под seed.

    max_pages принят ради совместимости контракта, но ИГНОРИРУЕТСЯ: у
    possible_job_offers нет пагинации.

    vacancy_id (seed) исключается из результата; если seed пуст — список всё
    равно собирается, а диагностический вызов suitable_resumes пропускается.

    Ошибки: на possible_job_offers fallback-статусы (0 сеть / 401 / 403 /
    5xx) перекидываются MobileAPIError наверх (для повтора через web-flow);
    прочие не-2xx (404 и т.п.) — пустой список. Ошибки диагностического
    suitable_resumes глотаются все и на результат не влияют.
    """
    seed_vid = str(vacancy_id or "")
    try:
        data = mobile_request(acc, "GET", "/vacancies/possible_job_offers")
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # 0 (сеть) / 401 / 403 / 5xx: не глотим — fallback-обёртка
            # повторит через web-flow (там настоящий seed-based шард).
            raise
        log_debug(f"mobile fetch_related_vacancies: possible_job_offers "
                  f"HTTP {e.status_code} | {e.payload}")
        data = []

    out = _collect_offer_vacancy_ids(data, seed_vid)

    if seed_vid:
        _diagnose_suitable_resumes(acc, seed_vid)

    return out
