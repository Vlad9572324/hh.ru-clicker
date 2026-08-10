"""Mobile-версия получения переговоров/откликов hh.ru (Phase 2).

GET https://api.hh.ru/negotiations (OAuth Bearer + mobile-заголовки через
app.hh_mobile_transport.mobile_request), пагинация до конца. Возвращает
dict, совместимый по ключам с web-аналогом
app.hh_negotiations.fetch_hh_negotiations_stats — чтобы фабрика клиентов
могла прозрачно fallback'нуть на web-flow.

Формат item — по официальному /negotiations/{topic_id} (см.
scratchpad/apidocs/apidocs_group_1.yaml): id, state{id,name}, created_at,
viewed_by_opponent, has_new_messages, vacancy{name}, ...
"""

import re
from datetime import datetime, timedelta

from app.hh_mobile_transport import (
    MOBILE_BASE,
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug

_NEGOTIATIONS_URL = MOBILE_BASE + "/negotiations"
_RECENT_WINDOW_DAYS = 60


def _parse_created_at(raw) -> datetime | None:
    """Распарсить created_at переговоров в aware datetime (None если не вышло).

    HH отдаёт смещение в виде "+0300" (без двоеточия) — fromisoformat
    в Python 3.10 такой формат не понимает, предварительно нормализуем.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip().replace("Z", "+00:00")
    s = re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive считаем локальным временем
    return dt


def fetch_negotiations(acc: dict, max_pages: int = 20, per_page: int = 100) -> dict:
    """Списать переговоры/отклики аккаунта через mobile GET /negotiations.

    Пагинированно (page=0..max_pages-1) запрашивает список и собирает
    статистику в dict с теми же ключами, что и web-аналог
    fetch_hh_negotiations_stats (совместимость для fallback):
    interview, recent_interview (за последние 60 дней), viewed, not_viewed,
    discard, interviews_list, neg_ids, discard_neg_ids, auth_error,
    unread_by_employer. Останавливается досрочно, если items пусты или
    достигнут found.

    Ошибки: fallback-статусы (0/401/403/5xx, см. is_fallback_status) →
    MobileAPIError поднимается выше — FallbackHHClient прозрачно повторяет
    запрос через web-flow (там же формируется auth_error, если web-сессия
    тоже мертва); прочие 4xx → возвращает dict с тем, что успел собрать.
    Ключ auth_error сохранён ради совместимости с web-формой; в mobile-пути
    всегда False.
    """
    result: dict = {
        "interview": 0,
        "recent_interview": 0,  # только последние 60 дней
        "viewed": 0,
        "not_viewed": 0,
        "discard": 0,
        "interviews_list": [],
        "neg_ids": [],
        "discard_neg_ids": [],  # id DISCARD-переговоров — LLM их пропускает без вызова API
        "auth_error": False,
        "unread_by_employer": 0,  # число переговоров с непрочитанными HR сообщениями
    }
    cutoff = datetime.now().astimezone() - timedelta(days=_RECENT_WINDOW_DAYS)
    seen_ids: set = set()  # дедуп при битой пагинации HH
    found = 0
    collected = 0

    for page in range(max_pages):
        try:
            data = mobile_request(
                acc, "GET", _NEGOTIATIONS_URL,
                params={"per_page": per_page, "page": page},
            )
        except MobileAPIError as e:
            if is_fallback_status(e.status_code):
                raise  # 0/401/403/5xx → fallback на web-flow выше по стеку
            log_debug(f"mobile fetch_negotiations page={page}: HTTP {e.status_code}")
            break

        if not isinstance(data, dict):
            break
        if page == 0:
            try:
                found = int(data.get("found") or 0)
            except (TypeError, ValueError):
                found = 0
        items = data.get("items") or []
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            neg_id = item.get("id")
            if neg_id is not None:
                if neg_id in seen_ids:
                    continue  # уже видели этот чат на предыдущей странице
                seen_ids.add(neg_id)
                result["neg_ids"].append(neg_id)

            state = item.get("state")
            state_id = state.get("id") if isinstance(state, dict) else None
            created_dt = _parse_created_at(item.get("created_at"))

            if state_id == "interview":
                result["interview"] += 1
                is_recent = created_dt >= cutoff if created_dt else True
                date_str = created_dt.strftime("%d.%m") if created_dt else ""
                if is_recent:
                    result["recent_interview"] += 1
                vacancy = item.get("vacancy")
                vacancy_name = str(vacancy.get("name") or "") if isinstance(vacancy, dict) else ""
                result["interviews_list"].append({
                    "neg_id": neg_id,
                    "date": date_str,
                    "text": vacancy_name[:120],
                    "recent": is_recent,
                })
            elif state_id == "discard":
                result["discard"] += 1
                if neg_id is not None:
                    result["discard_neg_ids"].append(neg_id)

            # Просмотр работодателем — только если поле реально присутствует
            if "viewed_by_opponent" in item:
                if item.get("viewed_by_opponent"):
                    result["viewed"] += 1
                else:
                    result["not_viewed"] += 1

            # Непрочитанные HR'ом: точное поле, иначе флаг has_new_messages
            unread_count = item.get("unread_by_employer_count")
            if isinstance(unread_count, int) and not isinstance(unread_count, bool):
                if unread_count > 0:
                    result["unread_by_employer"] += 1
            elif item.get("has_new_messages"):
                result["unread_by_employer"] += 1

        collected += len(items)
        if found and collected >= found:
            break
        if len(items) < per_page:
            break  # последняя страница

    return result
