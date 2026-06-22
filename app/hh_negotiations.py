"""
HH.ru negotiations: fetch stats, possible offers, auto-decline discards.
"""

import re
import requests
from datetime import datetime, timedelta

from app.logging_utils import log_debug, _is_login_page
from app.hh_resume import parse_hh_lux_ssr
from app.config import hh_base


def fetch_hh_negotiations_stats(acc: dict, max_pages: int = 20) -> dict:
    """Получить статистику откликов с hh.ru (парсинг HTML)"""
    cookies = acc["cookies"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": hh_base() + "/applicant/negotiations",
    }

    result = {
        "interview": 0,
        "recent_interview": 0,  # только последние 60 дней
        "viewed": 0,
        "not_viewed": 0,
        "discard": 0,
        "interviews_list": [],
        "neg_ids": [],
        "discard_neg_ids": [],  # chatId DISCARD-переговоров — LLM их пропускает без вызова API
        "auth_error": False,
        "unread_by_employer": 0,  # count of negotiations where employer hasn't read our messages
    }
    cutoff = datetime.now().astimezone() - timedelta(days=60)
    seen_interview_ids: set = set()  # для дедупа при битой пагинации HH

    # ── Шаг 1: точный счёт интервью через state=INTERVIEW фильтр ──────────────
    for page in range(max_pages):
        try:
            resp = requests.get(
                f"{hh_base()}/applicant/negotiations?filter=all&state=INTERVIEW&page={page}",
                cookies=cookies,
                headers=headers,
                timeout=15,
            )
            if resp.status_code != 200:
                if resp.status_code in (401, 403) or _is_login_page(resp.text):
                    result["auth_error"] = True
                break
            body = resp.text
            if _is_login_page(body):
                result["auth_error"] = True
                break

            # Extract negotiation IDs: HH renders items as buttons (no href links),
            # IDs are stored as chatId in the page's embedded JSON
            page_neg_ids = re.findall(r'"chatId"\s*:\s*"?(\d+)"?', body)
            for nid in page_neg_ids:
                if nid not in result["neg_ids"]:
                    result["neg_ids"].append(nid)

            parts = re.split(r'''data-qa\s*=\s*["']negotiations-item["']''', body)
            if len(parts) <= 1:
                break

            items_on_page = 0
            new_items_on_page = 0
            for item in parts[1:]:
                items_on_page += 1
                item = re.sub(r'^[^>]*>', '', item, count=1)

                # chatId per item — дедуп по нему, чтобы повторная страница не накручивала interview
                neg_id_match = re.search(r'"chatId"\s*:\s*"?(\d+)"?', item)
                item_neg_id = neg_id_match.group(1) if neg_id_match else ""
                if item_neg_id:
                    if item_neg_id in seen_interview_ids:
                        continue  # уже видели этот чат на предыдущей странице
                    seen_interview_ids.add(item_neg_id)
                    if item_neg_id not in result["neg_ids"]:
                        result["neg_ids"].append(item_neg_id)
                new_items_on_page += 1
                result["interview"] += 1

                # Извлекаем текст для списка
                clean = re.sub(r'<svg[\s\S]*?</svg>', '', item)
                clean = re.sub(r'<[^>]*>', ' ', clean, flags=re.DOTALL)
                clean = re.sub(r'\s+', ' ', clean).strip()
                text_body = re.sub(r'^(Собеседование|Приглашение|Интервью)\s*', '', clean)
                text_body = re.split(
                    r'\s+(?:сегодня\b|вчера\b|Был\s+онлайн|позавчера\b|\d+\s+\w+\s+назад)',
                    text_body
                )[0].strip()

                date_match = re.search(r'datetime="([^"]+)"', item)
                date_str = ""
                is_recent = True
                if date_match:
                    date_raw = date_match.group(1)
                    try:
                        dt = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
                        date_str = dt.strftime("%d.%m")
                        is_recent = dt >= cutoff
                    except ValueError:
                        m = re.search(r'(\d{4}-\d{2}-\d{2})', date_raw)
                        if m:
                            dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=cutoff.tzinfo)
                            date_str = dt.strftime("%d.%m")
                            is_recent = dt >= cutoff
                        else:
                            date_str = date_raw[:10]
                        log_debug(f"fetch_hh_negotiations_stats: unsupported date format {date_raw!r}")
                if is_recent:
                    result["recent_interview"] += 1
                result["interviews_list"].append({
                    "text": text_body[:120],
                    "date": date_str,
                    "recent": is_recent,
                    "neg_id": item_neg_id,
                })

            if items_on_page == 0 or new_items_on_page == 0:
                # либо страница пустая, либо HH вернул дубликаты предыдущей
                break

        except Exception as e:
            log_debug(f"fetch_hh_negotiations_stats interviews page={page} error: {e}")
            break

    if result["auth_error"]:
        return result

    # ── Шаг 2: просмотры / отказы с общей страницы ────────────────────────────
    seen_general_keys: set = set()
    for page in range(max_pages):
        try:
            resp = requests.get(
                f"{hh_base()}/applicant/negotiations?page={page}",
                cookies=cookies,
                headers=headers,
                timeout=15,
            )
            if resp.status_code != 200:
                break
            body = resp.text
            if _is_login_page(body):
                break

            # On first page, extract SSR data for conversationUnreadByEmployerCount
            if page == 0:
                try:
                    ssr = parse_hh_lux_ssr(body)
                    topic_list = ssr.get("topicList", [])
                    if isinstance(topic_list, list):
                        for topic in topic_list:
                            if isinstance(topic, dict):
                                cnt = topic.get("conversationUnreadByEmployerCount", 0)
                                if isinstance(cnt, int) and cnt > 0:
                                    result["unread_by_employer"] += 1
                except Exception:
                    pass

            parts = re.split(r'''data-qa\s*=\s*["']negotiations-item["']''', body)
            if len(parts) <= 1:
                break

            items_on_page = 0
            new_items_on_page = 0
            for item in parts[1:]:
                items_on_page += 1
                # Primary signal: CSS status classes (before stripping tag)
                status_class = ""
                cls_m = re.search(r'''class\s*=\s*["']([^"']*negotiations-item-[^"']*)["']''', item)
                if cls_m:
                    cls = cls_m.group(1)
                    if 'negotiations-item-discard' in cls:
                        status_class = 'discard'
                    elif 'negotiations-item-viewed' in cls:
                        status_class = 'viewed'
                    elif 'negotiations-item-interview' in cls or 'negotiations-item-invitation' in cls:
                        status_class = 'interview'

                item = re.sub(r'^[^>]*>', '', item, count=1)
                # Dedup by chatId — HH иногда повторяет страницы
                neg_id_match = re.search(r'"chatId"\s*:\s*"?(\d+)"?', item)
                key = neg_id_match.group(1) if neg_id_match else f"page{page}_idx{items_on_page}"
                if key in seen_general_keys:
                    continue
                seen_general_keys.add(key)
                new_items_on_page += 1

                if status_class == 'discard':
                    result["discard"] += 1
                    # Сохраняем chatId DISCARD-переговоров — LLM их пропустит без вызова.
                    if neg_id_match:
                        result["discard_neg_ids"].append(neg_id_match.group(1))
                elif status_class == 'viewed':
                    result["viewed"] += 1
                elif status_class == 'interview':
                    pass  # already counted in step 1
                else:
                    clean = re.sub(r'<svg[\s\S]*?</svg>', '', item)
                    clean = re.sub(r'<[^>]*>', ' ', clean, flags=re.DOTALL)
                    clean = re.sub(r'\s+', ' ', clean).strip()
                    first_word = clean.split(' ')[0] if clean else ''

                    if first_word in ('Отказ', 'Отклонено', 'Отклонён'):
                        result["discard"] += 1
                    elif clean.startswith('Просмотрен'):
                        result["viewed"] += 1
                    elif first_word not in ('Собеседование', 'Приглашение', 'Интервью'):
                        result["not_viewed"] += 1

            if items_on_page == 0 or new_items_on_page == 0:
                break

        except Exception as e:
            log_debug(f"fetch_hh_negotiations_stats general page={page} error: {e}")
            break

    return result


def fetch_hh_possible_offers(acc: dict) -> list:
    """Получить список компаний, готовых пригласить (JSON API)"""
    cookies = acc["cookies"]
    xsrf = cookies.get("_xsrf", "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-XsrfToken": xsrf,
        "Accept": "application/json",
        "Referer": hh_base() + "/applicant/negotiations",
    }
    try:
        resp = requests.get(
            hh_base() + "/shards/applicant/negotiations/possible_job_offers",
            cookies=cookies,
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            offers = []
            for item in data if isinstance(data, list) else data.get("items", []):
                name = item.get("name", "")
                vacancy_names = [v.get("name", "") for v in item.get("vacancies", [])]
                offers.append({"name": name, "vacancyNames": vacancy_names})
            return offers
    except Exception as e:
        log_debug(f"fetch_hh_possible_offers error: {e}")
    return []


def auto_decline_discards(acc: dict) -> int:
    """
    Авто-отклонение дискардов в переговорах.
    Возвращает количество отклонённых.
    """
    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    if not xsrf:
        return 0
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": hh_base() + "/applicant/negotiations",
        "X-Xsrftoken": xsrf,
    }
    declined = 0
    try:
        # Собираем topic_id дискардов (первые 5 страниц)
        topic_ids = []
        for page in range(5):
            r = requests.get(
                f"{hh_base()}/applicant/negotiations?state=DISCARD&page={page}",
                headers=headers, cookies=acc["cookies"], timeout=15
            )
            ssr = parse_hh_lux_ssr(r.text)
            topics = ssr.get("applicantNegotiations", {}).get("topicList", [])
            if not topics:
                break
            for topic in topics:
                actions = topic.get("actions", [])
                for action in actions:
                    if action.get("id") == "decline" or "decline" in action.get("url", ""):
                        topic_ids.append(str(topic.get("id", "")))
                        break
            if len(topics) < 10:
                break

        # Отклоняем
        for tid in topic_ids[:50]:  # не более 50 за раз
            try:
                # requests сам сделает URL-encoding (важно: _xsrf может содержать `+`, `=`, `&`)
                r2 = requests.post(
                    hh_base() + "/applicant/negotiations/decline",
                    headers=headers,
                    cookies=acc["cookies"],
                    data={"topicId": tid, "_xsrf": xsrf},
                    timeout=10
                )
                if r2.status_code in (200, 302):
                    declined += 1
            except Exception as e:
                log_debug(f"auto_decline_discards POST {tid}: {e}")
    except Exception as e:
        log_debug(f"auto_decline_discards error: {e}")
    return declined


# ── Employer ratings (employer_reviews/proxy_components/small_widget) ──
# Reverse-engineered from /employer/{id} SSR microFrontends config.
# Один JSON-вызов отдаёт: totalRating (1-5), recommendationsPercent,
# 6 категорий (workplace/team/management/career/rest/salary),
# топ advantages с counts, общее число отзывов, негативных.
# Используется для показа «Яндекс ⭐4.3 (81%)» рядом с employer name.

import threading as _t_emp
import time as _time_emp

_EMPLOYER_RATING_CACHE: dict = {}  # employer_id → (cached_at_ts, data|None)
_EMPLOYER_RATING_TTL = 24 * 3600   # 24ч (рейтинг меняется медленно)
_EMPLOYER_RATING_LOCK = _t_emp.Lock()
_EMPLOYER_RATING_NULL_TTL = 3600   # отрицательные ответы кэшируем час


def fetch_employer_rating(acc: dict, employer_id) -> dict | None:
    """GET /employer_reviews/proxy_components/small_widget?employerId=N.

    Возвращает компактный dict {total, recommend_pct, ratings, advantages,
    reviews_count, neg_count, staff_count, status} или None если работодатель
    закрыт/без отзывов. Все вызовы кэшируются в памяти на 24ч.
    """
    try:
        eid = int(str(employer_id).strip())
    except (ValueError, TypeError):
        return None
    if eid <= 0:
        return None
    now = _time_emp.time()
    with _EMPLOYER_RATING_LOCK:
        hit = _EMPLOYER_RATING_CACHE.get(eid)
        if hit:
            cached_at, data = hit
            ttl = _EMPLOYER_RATING_TTL if data else _EMPLOYER_RATING_NULL_TTL
            if now - cached_at < ttl:
                return data

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"
    try:
        import requests as _rq
        r = _rq.get(
            f"{hh_base()}/employer_reviews/proxy_components/small_widget",
            params={"employerId": eid},
            cookies=acc.get("cookies") or {},
            headers={
                "User-Agent": ua,
                "Accept": "application/json",
                "Referer": f"{hh_base()}/employer/{eid}",
            },
            timeout=10,
        )
        if r.status_code != 200 or "json" not in r.headers.get("Content-Type", ""):
            with _EMPLOYER_RATING_LOCK:
                _EMPLOYER_RATING_CACHE[eid] = (now, None)
            return None
        body = r.json() or {}
    except Exception as e:
        log_debug(f"fetch_employer_rating({eid}): {e}")
        with _EMPLOYER_RATING_LOCK:
            _EMPLOYER_RATING_CACHE[eid] = (now, None)
        return None

    rev = body.get("employerReviews") or {}
    if not rev or not rev.get("totalRating"):
        with _EMPLOYER_RATING_LOCK:
            _EMPLOYER_RATING_CACHE[eid] = (now, None)
        return None

    # Compact projection — то что реально нужно UI
    try:
        total = float(rev.get("totalRating") or 0)
    except (ValueError, TypeError):
        total = 0.0
    ratings = {x.get("id"): x.get("value") for x in (rev.get("ratings") or []) if isinstance(x, dict)}
    advantages = [
        {"name": a.get("name", ""), "count": a.get("count", 0)}
        for a in (rev.get("advantages") or [])[:3] if isinstance(a, dict)
    ]
    name = (body.get("employerNameMap") or {}).get(str(eid)) or ""
    compact = {
        "id": eid,
        "name": name,
        "total": round(total, 1),
        "recommend_pct": rev.get("recommendationsPercent"),
        "ratings": {
            "workplace": ratings.get("WORKPLACE"),
            "team": ratings.get("TEAM"),
            "management": ratings.get("MANAGEMENT"),
            "career": ratings.get("CAREER"),
            "rest": ratings.get("REST_RECOVERY"),
            "salary": ratings.get("SALARY"),
        },
        "advantages": advantages,
        "reviews_count": rev.get("reviewsCount", 0),
        "neg_count": rev.get("negativeReviewsCount", 0),
        "staff_count": rev.get("staffCount", ""),  # STAFF_COUNT_MORE_10000 etc.
        "status": rev.get("activityStatus", ""),    # ACTIVE_EMPLOYER / etc.
        "is_open": rev.get("isOpenEmployer", False),
    }
    with _EMPLOYER_RATING_LOCK:
        _EMPLOYER_RATING_CACHE[eid] = (now, compact)
    return compact


# Кэш vacancy_id → employer_id. Меняется крайне редко (когда вакансия
# переезжает между юр.лицами), TTL 7 дней нормально.
_VACANCY_EMPLOYER_CACHE: dict = {}
_VACANCY_EMPLOYER_TTL = 7 * 24 * 3600
_VACANCY_EMPLOYER_LOCK = _t_emp.Lock()


def fetch_employer_id_for_vacancy(acc: dict, vacancy_id) -> int | None:
    """Достать employerId по vacancy_id через SSR /vacancy/{vid} → vacancyView.employer.id.
    Кэш на 7 дней. None если страница недоступна или вакансия снята.
    """
    try:
        vid = int(str(vacancy_id).strip())
    except (ValueError, TypeError):
        return None
    if vid <= 0:
        return None
    now = _time_emp.time()
    with _VACANCY_EMPLOYER_LOCK:
        hit = _VACANCY_EMPLOYER_CACHE.get(vid)
        if hit:
            cached_at, eid = hit
            if now - cached_at < _VACANCY_EMPLOYER_TTL:
                return eid

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"
    try:
        import requests as _rq
        r = _rq.get(
            f"{hh_base()}/vacancy/{vid}",
            cookies=acc.get("cookies") or {},
            headers={"User-Agent": ua, "Accept": "text/html", "Referer": hh_base() + "/"},
            timeout=12, allow_redirects=True,
        )
        if r.status_code != 200:
            with _VACANCY_EMPLOYER_LOCK:
                _VACANCY_EMPLOYER_CACHE[vid] = (now, None)
            return None
        from app.hh_resume import parse_hh_lux_ssr
        ssr = parse_hh_lux_ssr(r.text)
        vv = ssr.get("vacancyView") or {}
        # HH мигрировали с vacancyView.employer на vacancyView.company —
        # держим оба варианта на случай отката или регионального различия.
        co = vv.get("company") or vv.get("employer") or {}
        eid = co.get("id") or co.get("mainEmployerId")
        if isinstance(eid, str):
            try: eid = int(eid)
            except (ValueError, TypeError): eid = None
        with _VACANCY_EMPLOYER_LOCK:
            _VACANCY_EMPLOYER_CACHE[vid] = (now, eid)
        return eid
    except Exception as e:
        log_debug(f"fetch_employer_id_for_vacancy({vid}): {e}")
        with _VACANCY_EMPLOYER_LOCK:
            _VACANCY_EMPLOYER_CACHE[vid] = (now, None)
        return None


def fetch_rating_by_vacancy(acc: dict, vacancy_id) -> dict | None:
    """Цепочка vid → employerId → rating. Возвращает rating-dict (см.
    fetch_employer_rating) или None.
    """
    eid = fetch_employer_id_for_vacancy(acc, vacancy_id)
    if not eid:
        return None
    return fetch_employer_rating(acc, eid)


# Кэш метаданных переговоров: politeness (per-employer % чтения и дни ответа)
# + activity (per-HR онлайн-статус). Одним SSR-запросом /applicant/negotiations
# получаем всё — обновляем раз в час.
_NEG_META_CACHE: dict = {}  # acc_key → (cached_at, {politeness, activity})
_NEG_META_TTL = 3600
_NEG_META_LOCK = _t_emp.Lock()


def fetch_negotiations_metadata(acc: dict) -> dict:
    """Достать politeness + HR activity + per-topic статусы из
    /applicant/negotiations SSR.

    politeness: {employer_id: {read_percent, reply_days, total_topics}}
    activity:   {hr_hhid: {trl_code, inactive_minutes, inactive_days}}
    topics_by_vid: {vacancy_id: {viewed_by_opponent, unread_by_employer,
                                last_state, has_pending_survey, has_new_messages,
                                inbox_availability_state}}
    Кэш 1ч (per acc identity). Все 3 источника достаются одним SSR-запросом.
    """
    # Идентификатор аккаунта — hhuid + hhtoken hash (стабильный для сессии)
    cookies = acc.get("cookies") or {}
    acc_key = (cookies.get("hhuid") or "") + ":" + (cookies.get("hhtoken","") or "")[:16]
    if not acc_key:
        return {"politeness": {}, "activity": {}, "topics_by_vid": {}}
    now = _time_emp.time()
    with _NEG_META_LOCK:
        hit = _NEG_META_CACHE.get(acc_key)
        if hit and now - hit[0] < _NEG_META_TTL:
            return hit[1]

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"
    out = {"politeness": {}, "activity": {}, "topics_by_vid": {}}
    try:
        import requests as _rq
        r = _rq.get(
            f"{hh_base()}/applicant/negotiations",
            cookies=cookies,
            headers={"User-Agent": ua, "Accept": "text/html", "Referer": hh_base() + "/"},
            timeout=15, allow_redirects=True,
        )
        if r.status_code != 200:
            return out
        from app.hh_resume import parse_hh_lux_ssr
        ssr = parse_hh_lux_ssr(r.text)
        pol_idx = (ssr.get("applicantEmployerPoliteness") or {}).get("employerPolitenessIndexes") or {}
        for _, p in pol_idx.items():
            if not isinstance(p, dict): continue
            eid = p.get("employerId")
            if not eid: continue
            out["politeness"][int(eid)] = {
                "read_percent": p.get("readTopicPercent"),
                "reply_days": p.get("replyTotalWorkingTimeDays"),
                "total_topics": p.get("allTopicCount"),
            }
        for a in (ssr.get("applicantEmployerManagersActivity") or []):
            if not isinstance(a, dict): continue
            hhid = a.get("@managerHhid")
            if not hhid: continue
            out["activity"][int(hhid)] = {
                "trl_code": a.get("trl_code", ""),
                "inactive_minutes": a.get("@inactiveMinutes"),
                "inactive_days": a.get("inactive_days"),
            }
        # Per-topic статусы из applicantNegotiations.topicList: ключевая инфа —
        # увидел ли HR наше сообщение (viewedByOpponent) и сколько у него
        # непрочитанных от нас (conversationUnreadByEmployerCount).
        an = ssr.get("applicantNegotiations") or {}
        for t in (an.get("topicList") or []):
            if not isinstance(t, dict): continue
            vid = t.get("vacancyId")
            if not vid: continue
            out["topics_by_vid"][str(vid)] = {
                "viewed_by_opponent": bool(t.get("viewedByOpponent")),
                "unread_by_employer": t.get("conversationUnreadByEmployerCount", 0),
                "last_state": t.get("lastState", ""),
                "has_pending_survey": bool(t.get("hasPendingAutoActionSurvey")),
                "has_new_messages": bool(t.get("hasNewMessages")),
                "inbox_availability_state": t.get("inboxAvailabilityState", ""),
                "applicant_summary_enabled": bool(t.get("applicantVacancySummaryEnabled")),
            }
    except Exception as e:
        log_debug(f"fetch_negotiations_metadata: {e}")
    with _NEG_META_LOCK:
        _NEG_META_CACHE[acc_key] = (now, out)
    return out


# Кэш vacancy_id → owner HR's @managerHhid (из vacancyInternalInfo).
# Меняется ОЧЕНЬ редко, TTL 7 дней.
_VACANCY_HR_CACHE: dict = {}
_VACANCY_HR_LOCK = _t_emp.Lock()


def fetch_vacancy_owner_hr_hhid(acc: dict, vacancy_id) -> int | None:
    """Кто конкретно (HR) опубликовал эту вакансию. Возвращает их @managerHhid."""
    try:
        vid = int(str(vacancy_id).strip())
    except (ValueError, TypeError):
        return None
    if vid <= 0:
        return None
    now = _time_emp.time()
    with _VACANCY_HR_LOCK:
        hit = _VACANCY_HR_CACHE.get(vid)
        if hit and now - hit[0] < _VACANCY_EMPLOYER_TTL:
            return hit[1]
    ua = "Mozilla/5.0 Chrome/120"
    try:
        import requests as _rq
        r = _rq.get(
            f"{hh_base()}/vacancy/{vid}",
            cookies=acc.get("cookies") or {},
            headers={"User-Agent": ua, "Accept": "text/html"},
            timeout=10, allow_redirects=True,
        )
        if r.status_code != 200:
            return None
        from app.hh_resume import parse_hh_lux_ssr
        ssr = parse_hh_lux_ssr(r.text)
        vii = ssr.get("vacancyInternalInfo") or {}
        hhid = vii.get("ownerEmployerManagerHhid")
        if isinstance(hhid, str):
            try: hhid = int(hhid)
            except (ValueError, TypeError): hhid = None
        with _VACANCY_HR_LOCK:
            _VACANCY_HR_CACHE[vid] = (now, hhid)
        return hhid
    except Exception as e:
        log_debug(f"fetch_vacancy_owner_hr_hhid({vid}): {e}")
        return None
