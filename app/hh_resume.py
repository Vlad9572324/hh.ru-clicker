"""
HH.ru resume functions: parse, fetch, analyze, edit resume.
"""

import re
import json
import time
import threading
import urllib.parse
import requests

from bs4 import BeautifulSoup

from app.logging_utils import log_debug, _is_login_page
from app.config import CONFIG, hh_base

_resume_cache: dict = {}   # {resume_hash: (text, timestamp)}
# RLock — reentrant: fetch_resume_text держит лок, потом вызывает _cleanup_resume_cache,
# который тоже хочет его взять. С Lock — deadlock; с RLock одна и та же нитка проходит.
_resume_cache_lock = threading.RLock()
_RESUME_CACHE_TTL = 4 * 3600  # 4 hours
_RESUME_CACHE_MAX = 200


def _cleanup_resume_cache(now: float):
    """Remove expired entries and enforce size cap."""
    with _resume_cache_lock:
        # Expired cleanup (max 50 per call)
        expired = [k for k, (_, ts) in list(_resume_cache.items()) if now - ts >= _RESUME_CACHE_TTL]
        for k in expired[:50]:
            _resume_cache.pop(k, None)
        # Size cap: evict oldest 50 by timestamp if over limit
        if len(_resume_cache) > _RESUME_CACHE_MAX:
            sorted_items = sorted(_resume_cache.items(), key=lambda x: x[1][1])
            for k, _ in sorted_items[:50]:
                _resume_cache.pop(k, None)


def parse_hh_lux_ssr(html: str) -> dict:
    """Извлечь SSR JSON из <template id="HH-Lux-InitialState">"""
    m = re.search(r'<template[^>]*id="HH-Lux-InitialState"[^>]*>([\s\S]*?)</template>', html)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception as e:
        log_debug(f"parse_hh_lux_ssr error: {e}")
        return {}


def _hh_ssr_str(val) -> str:
    """Извлечь строку из поля HH SSR, которое может быть str, dict или list[dict]."""
    if isinstance(val, str):
        return val
    if isinstance(val, list) and val:
        first = val[0]
        if isinstance(first, dict):
            return str(first.get("string") or first.get("text") or first.get("name") or "")
        return str(first)
    if isinstance(val, dict):
        return str(val.get("string") or val.get("text") or val.get("value") or val.get("name") or "")
    return ""


def _parse_resume_ssr(ssr: dict) -> str:
    """Извлечь текст резюме из SSR JSON страницы резюме HH.ru."""
    resume: dict = {}
    for key in ("applicantResume", "resume", "resumeView"):
        val = ssr.get(key)
        if isinstance(val, dict) and val and not val.get("forbidden"):
            resume = val
            break
    if not resume:
        return ""

    parts = []

    # Name (optional context)
    first = _hh_ssr_str(resume.get("firstName"))
    last = _hh_ssr_str(resume.get("lastName"))
    full_name = " ".join(p for p in [first, last] if p)

    # Desired position — HH stores as [{"string": "..."}]
    title = _hh_ssr_str(resume.get("title"))
    # Also check professionalRole for named roles
    roles = resume.get("professionalRole") or []
    role_names = [r.get("text") for r in roles if isinstance(r, dict) and r.get("text")]
    position_line = title or ", ".join(role_names[:3])
    if position_line:
        parts.append(f"Желаемая должность: {position_line}")

    # Key skills — advancedKeySkills has name field; keySkills has {string: ...}
    adv_skills = resume.get("advancedKeySkills") or []
    if adv_skills and isinstance(adv_skills, list):
        skill_names = [s["name"] for s in adv_skills if isinstance(s, dict) and s.get("name")]
    else:
        raw_skills = resume.get("keySkills") or []
        skill_names = [_hh_ssr_str(s) for s in raw_skills if _hh_ssr_str(s)]
    if skill_names:
        parts.append(f"Ключевые навыки: {', '.join(skill_names[:30])}")

    # Experience
    experience = resume.get("experience") or []
    if experience and isinstance(experience, list):
        exp_parts = ["Опыт работы:"]
        for job in experience[:5]:
            if not isinstance(job, dict):
                continue
            company = str(job.get("companyName") or "")
            position = str(job.get("position") or "")
            description = str(job.get("description") or "")[:200]
            start = str(job.get("startDate") or "")[:7]   # "2024-01"
            end = str(job.get("endDate") or "")[:7] or "н.вр."
            period = f"{start}–{end}" if start else ""
            entry_parts = [p for p in [company, position] if p]
            if period:
                entry_parts.append(period)
            if description:
                entry_parts.append(f"({description})")
            if entry_parts:
                exp_parts.append("  " + " | ".join(entry_parts))
        if len(exp_parts) > 1:
            parts.append("\n".join(exp_parts))

    # Education
    edu_items = resume.get("primaryEducation") or resume.get("additionalEducation") or []
    if edu_items and isinstance(edu_items, list):
        edu_names = []
        for e in edu_items[:3]:
            if not isinstance(e, dict):
                continue
            uni = e.get("universityAcronym") or e.get("name") or ""
            org = e.get("organization") or ""
            result = e.get("result") or ""
            year = e.get("year") or ""
            if uni or result:
                edu_names.append(
                    f"{uni}" + (f" ({org})" if org and org != uni else "")
                    + (f" — {result}" if result else "")
                    + (f", {year}" if year else "")
                )
        if edu_names:
            parts.append(f"Образование: {'; '.join(edu_names)}")

    return "\n\n".join(parts)


def _parse_resume_html(html: str) -> str:
    """Извлечь текст резюме из HTML страницы HH.ru."""
    # Try SSR JSON first (cleaner structured data)
    ssr = parse_hh_lux_ssr(html)
    if ssr:
        result = _parse_resume_ssr(ssr)
        if result:
            return result

    # Fallback: BeautifulSoup HTML parsing
    soup = BeautifulSoup(html, "html.parser")
    parts = []

    # Desired position
    title_el = soup.find(attrs={"data-qa": "resume-block-title-position"})
    if title_el:
        parts.append(f"Желаемая должность: {title_el.get_text(strip=True)}")

    # Key skills
    skill_els = soup.find_all(attrs={"data-qa": "bloko-tag__text"})
    if not skill_els:
        skill_els = soup.find_all(attrs={"data-qa": "skills-element"})
    skills = [el.get_text(strip=True) for el in skill_els if el.get_text(strip=True)]
    if skills:
        parts.append(f"Ключевые навыки: {', '.join(skills[:30])}")

    # Experience
    exp_section = soup.find(attrs={"data-qa": "resume-block-experience"})
    if exp_section:
        exp_parts = ["Опыт работы:"]
        companies = exp_section.find_all(attrs={"data-qa": re.compile(
            r"resume-block-experience-company|resume-block-experience-name")})
        positions = exp_section.find_all(attrs={"data-qa": "resume-block-experience-position"})
        for i, company_el in enumerate(companies[:5]):
            co_text = company_el.get_text(strip=True)
            po_text = positions[i].get_text(strip=True) if i < len(positions) else ""
            entry = co_text + (f" — {po_text}" if po_text else "")
            exp_parts.append(f"  {entry}")
        if len(exp_parts) > 1:
            parts.append("\n".join(exp_parts))

    # About / additional
    for qa in ("resume-block-additional-resume", "resume-block-skills-content"):
        about_el = soup.find(attrs={"data-qa": qa})
        if about_el:
            about_text = about_el.get_text(" ", strip=True)[:500]
            if about_text:
                parts.append(f"О себе: {about_text}")
            break

    # Education
    edu_el = soup.find(attrs={"data-qa": "resume-block-education"})
    if edu_el:
        edu_text = edu_el.get_text(" ", strip=True)[:300]
        if edu_text:
            parts.append(f"Образование: {edu_text}")

    result = "\n\n".join(parts)
    # Last resort: strip all HTML, take leading 1500 chars of body text
    if not result:
        result = soup.get_text(" ", strip=True)[:1500]
    return result


def fetch_resume_text(acc: dict) -> str:
    """
    Получить текстовое представление резюме для LLM-контекста.
    Кэширует результат на 4 часа (_RESUME_CACHE_TTL).
    """
    resume_hash = acc.get("resume_hash", "")
    if not resume_hash:
        return ""

    now = time.time()
    with _resume_cache_lock:
        cached = _resume_cache.get(resume_hash)
        if cached:
            text, ts = cached
            if now - ts < _RESUME_CACHE_TTL:
                _cleanup_resume_cache(now)
                return text
    _cleanup_resume_cache(now)

    try:
        r = requests.get(
            f"{hh_base()}/resume/{resume_hash}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": hh_base() + "/applicant/resumes",
            },
            cookies=acc["cookies"],
            timeout=15,
        )
        if r.status_code != 200:
            log_debug(f"fetch_resume_text: HTTP {r.status_code} для {resume_hash[:8]}")
            return ""
        text = _parse_resume_html(r.text)
        if text:
            with _resume_cache_lock:
                _resume_cache[resume_hash] = (text, now)
            _cleanup_resume_cache(now)
            log_debug(f"fetch_resume_text: ✅ {len(text)} симв. для {resume_hash[:8]}")
        else:
            log_debug(f"fetch_resume_text: ⚠️ пустой результат для {resume_hash[:8]}")
        return text
    except Exception as e:
        log_debug(f"fetch_resume_text error: {e}")
        return ""


def fetch_resume_stats(acc: dict) -> dict:
    """
    Статистика резюме за 7 дней + точный таймер поднятия.
    Возвращает dict с ключами: views, views_new, shows, invitations, invitations_new,
    next_touch_seconds, free_touches, global_invitations, new_invitations_total
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": hh_base() + "/",
    }
    result = {
        "views": 0, "views_new": 0, "shows": 0,
        "invitations": 0, "invitations_new": 0,
        "next_touch_seconds": 0, "free_touches": 0,
        "global_invitations": 0, "new_invitations_total": 0,
    }
    try:
        r = requests.get(
            hh_base() + "/applicant/resumes",
            headers=headers, cookies=acc["cookies"], timeout=15
        )
        ssr = parse_hh_lux_ssr(r.text)

        # userStats counters
        user_stats = ssr.get("userStats", {})
        result["views_new"] = user_stats.get("new-resumes-views", 0)
        result["new_invitations_total"] = user_stats.get("new-applicant-invitations", 0)
        result["global_invitations"] = ssr.get("globalInvitations", 0)

        # Per-resume statistics
        # Structure: applicantResumesStatistics["resumes"][resume_id]["statistics"]
        stats_map = ssr.get("applicantResumesStatistics", {})
        resumes_stats = stats_map.get("resumes", {}) if isinstance(stats_map, dict) else {}
        for resume_id, data in resumes_stats.items():
            st = data.get("statistics", {})
            result["shows"] += (st.get("searchShows") or {}).get("count", 0)
            result["views"] += (st.get("views") or {}).get("count", 0)
            result["views_new"] = max(result["views_new"], (st.get("views") or {}).get("countNew", 0))
            result["invitations"] += (st.get("invitations") or {}).get("count", 0)
            result["invitations_new"] += (st.get("invitations") or {}).get("countNew", 0)

        # Точный таймер поднятия резюме
        resumes = ssr.get("applicantResumes", [])
        for res in resumes:
            to_update = res.get("toUpdate") or {}
            if "value" in to_update:
                result["next_touch_seconds"] = max(result["next_touch_seconds"], to_update["value"])
            if "count" in to_update:
                result["free_touches"] = to_update["count"]

    except Exception as e:
        log_debug(f"fetch_resume_stats error: {e}")
    return result


def fetch_resume_view_history(acc: dict, limit: int = 50) -> list:
    """
    Кто смотрел резюме.
    Возвращает list of {employer_id, name, date}
    """
    resume_hash = acc["resume_hash"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": hh_base() + "/applicant/resumes",
    }
    result = []
    try:
        r = requests.get(
            f"{hh_base()}/applicant/resumeview/history?resumeHash={resume_hash}",
            headers=headers, cookies=acc["cookies"], timeout=15
        )
        html = r.text

        # Парсим через SSR JSON
        ssr = parse_hh_lux_ssr(html)
        hist_data = ssr.get("applicantResumeViewHistory", {})
        hist_views = hist_data.get("historyViews", {})
        years_list = hist_views.get("years", []) if isinstance(hist_views, dict) else []
        for year_entry in years_list:
            for day_entry in year_entry.get("days", []):
                day   = day_entry.get("day", 0)
                month = day_entry.get("month", 0)
                year  = year_entry.get("year", 0)
                date_str = f"{year}-{month:02d}-{day:02d}"
                for company in day_entry.get("companies", []):
                    views_ts = company.get("views", [])
                    ts = views_ts[0][:10] if views_ts else date_str
                    result.append({
                        "employer_id": str(company.get("id", "")),
                        "name": company.get("name", "").strip() or "Аноним",
                        "date": ts,
                        "vacancy": "",
                    })
                    if len(result) >= limit:
                        break
                if len(result) >= limit:
                    break
            if len(result) >= limit:
                break

        # Fallback: парсим HTML если SSR пустой
        if not result:
            soup = BeautifulSoup(html, "html.parser")
            seen = set()
            for a in soup.find_all("a", href=re.compile(r"/employer/\d+")):
                m = re.search(r"/employer/(\d+)", a.get("href", ""))
                if not m:
                    continue
                employer_id = m.group(1)
                if employer_id in seen:
                    continue
                seen.add(employer_id)
                name = a.get_text(strip=True)
                date = ""
                # Walk siblings and parent to find a <time> tag
                for sibling in list(a.next_siblings) + list(a.parent.next_siblings if a.parent else []):
                    if sibling and getattr(sibling, "name", None) == "time":
                        date = sibling.get("datetime", "")[:10]
                        break
                    if sibling and getattr(sibling, "find", None):
                        t = sibling.find("time")
                        if t and t.get("datetime"):
                            date = t.get("datetime")[:10]
                            break
                result.append({
                    "employer_id": employer_id,
                    "name": name or "Аноним",
                    "date": date,
                    "vacancy": "",
                })
                if len(result) >= limit:
                    break
    except Exception as e:
        log_debug(f"fetch_resume_view_history error: {e}")
    return result


def _analyze_resume(acc: dict, extra_terms: list = None) -> dict:
    """Аудит резюме — что видит HR, что не заполнено, рекомендации."""
    resume_hash = acc.get("resume_hash", "")
    if not resume_hash:
        return {"error": "Нет resume_hash"}
    cookies = acc.get("cookies", {})
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    try:
        # 1. Fetch resume page SSR
        r = requests.get(
            f"{hh_base()}/resume/{resume_hash}",
            headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml"},
            cookies=cookies, timeout=15,
        )
        if r.status_code != 200 or _is_login_page(r.text):
            return {"error": "auth_error"}
        ssr = parse_hh_lux_ssr(r.text)
        resume = None
        for key in ("applicantResume", "resume", "resumeView"):
            val = ssr.get(key)
            if isinstance(val, dict) and val and not val.get("forbidden"):
                resume = val
                break
        if not resume:
            return {"error": "Не удалось получить данные резюме"}

        attrs = resume.get("_attributes", {})
        field_statuses = resume.get("fieldStatuses", {})

        # Helper
        def _str(val):
            if isinstance(val, list) and val:
                v = val[0]
                if isinstance(v, dict):
                    return v.get("string", v.get("text", v.get("name", str(v))))
                return str(v)
            return ""

        # 2. Fetch stats from resumes page
        r2 = requests.get(
            hh_base() + "/applicant/resumes",
            headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml"},
            cookies=cookies, timeout=15,
        )
        stats_data = {}
        if r2.status_code == 200:
            ssr2 = parse_hh_lux_ssr(r2.text)
            all_stats = ssr2.get("applicantResumesStatistics", {}).get("resumes", {})
            rid = str(attrs.get("id", ""))
            stats_data = all_stats.get(rid, {}).get("statistics", {})

        # 3. Build analysis
        job_status_raw = resume.get("jobSearchStatus", [])
        job_status = ""
        if job_status_raw and isinstance(job_status_raw, list):
            job_status = (job_status_raw[0].get("jobSearchStatus", {}).get("name", "") if isinstance(job_status_raw[0], dict) else "")

        title = _str(resume.get("title"))
        roles = [r.get("text", "") for r in resume.get("professionalRole", []) if isinstance(r, dict)]
        skills = [s.get("string", "") or s.get("name", "") for s in resume.get("keySkills", []) if isinstance(s, dict)]
        salary = resume.get("salary", [])
        salary_str = ""
        if salary and isinstance(salary[0], dict):
            amt = salary[0].get("amount") or salary[0].get("string")
            salary_str = str(amt) if amt else ""

        work_schedule = [_str([s]) for s in resume.get("workSchedule", [])]
        work_formats = [_str([s]) for s in resume.get("workFormats", [])]
        employment = [_str([s]) for s in resume.get("employment", [])]

        # Green fields = fields that could improve but not filled
        green = field_statuses.get("greenFields", [])
        red = field_statuses.get("redFields", [])

        # Recommendations
        issues = []
        if job_status == "not_looking_for_job":
            issues.append({"level": "critical", "text": "Статус «Не ищу работу» — HR пропускают такие резюме", "fix": "Поменять на «Активно ищу» или «Рассматриваю предложения»"})
        elif job_status == "looking_for_offers":
            issues.append({"level": "info", "text": "Статус «Рассматриваю предложения» — OK, но «Активно ищу» даёт больше показов"})

        percent = attrs.get("percent", 0)
        if percent and percent < 80:
            issues.append({"level": "high", "text": f"Заполненность {percent}% — HR видят это, нужно 80%+", "fix": "Заполнить пустые поля"})

        status = attrs.get("status", "")
        if status != "published":
            issues.append({"level": "critical", "text": f"Статус резюме: {status} (не опубликовано)", "fix": "Опубликовать резюме на hh.ru"})

        if not attrs.get("canPublishOrUpdate"):
            issues.append({"level": "high", "text": "Резюме нельзя обновить/опубликовать", "fix": "Проверить ограничения в настройках hh.ru"})

        if "photo" in green:
            issues.append({"level": "high", "text": "Нет фото — HR часто фильтруют «только с фото»", "fix": "Добавить деловое фото"})

        if "salary" in green or not salary_str:
            issues.append({"level": "medium", "text": "Не указана зарплата — HR не может фильтровать по ожиданиям", "fix": "Указать желаемую зарплату"})

        if "skills" in green:
            issues.append({"level": "medium", "text": "Не заполнено «О себе» — теряете очки в поиске", "fix": "Написать 3-5 предложений о себе"})

        if "email" in green:
            issues.append({"level": "low", "text": "Не указан email", "fix": "Добавить email для связи"})

        if "recommendation" in green:
            issues.append({"level": "low", "text": "Нет рекомендаций", "fix": "Попросить коллегу/руководителя оставить рекомендацию"})

        if "certificate" in green:
            issues.append({"level": "low", "text": "Нет сертификатов", "fix": "Добавить профильные сертификаты (курсы, экзамены)"})

        search_shows = (stats_data.get("searchShows") or {}).get("count", 0)
        views = (stats_data.get("views") or {}).get("count", 0)
        views_new = (stats_data.get("views") or {}).get("countNew", 0)
        invitations = (stats_data.get("invitations") or {}).get("count", 0)
        inv_new = (stats_data.get("invitations") or {}).get("countNew", 0)

        if search_shows < 5:
            issues.append({"level": "high", "text": f"Только {search_shows} показов в поиске за 7 дней — резюме плохо ранжируется", "fix": "Обновить резюме, поменять статус на «Активно ищу», поднять резюме"})

        _SCHEDULE_MAP = {"full_day": "Полный день", "remote": "Удалённая", "flexible": "Гибкий", "shift": "Сменный", "flyInFlyOut": "Вахта"}
        _FORMAT_MAP = {"ON_SITE": "Офис", "REMOTE": "Удалёнка", "HYBRID": "Гибрид", "FIELD_WORK": "Разъезды"}
        _EMPLOY_MAP = {"full": "Полная", "part": "Частичная", "project": "Проектная", "volunteer": "Волонтёрство", "probation": "Стажировка"}
        _STATUS_MAP = {
            "not_looking_for_job": "Не ищу работу",
            "looking_for_offers": "Рассматриваю предложения",
            "actively_searching": "Активно ищу работу",
            "has_job_offer": "Есть оффер",
            "accepted_job_offer": "Принял оффер",
        }

        # 4. Market analysis — competitor data and vacancy supply/demand
        market = {}
        try:
            # Use first role or first part of title for search
            search_term = (roles[0] if roles else title.split(",")[0].strip()) if title else ""
            encoded_title = urllib.parse.quote(search_term)
            # Fetch resume clusters (competitor counts)
            r_clusters = requests.get(
                f"{hh_base()}/shards/search/resume/clusters?text={encoded_title}&area=1",
                headers={"User-Agent": ua, "Accept": "application/json"},
                cookies=cookies, timeout=10,
            )
            clusters_data = {}
            active_seekers = 0
            experience_dist = []
            top_competitor_skills = []
            if r_clusters.status_code == 200:
                try:
                    cj = r_clusters.json()
                    clusters = cj.get("clusters", {})
                    exp_groups = clusters.get("experience", {}).get("groups", {})
                    for gid, gdata in exp_groups.items():
                        experience_dist.append({
                            "id": gid,
                            "name": gdata.get("title", gid),
                            "count": gdata.get("count", 0),
                        })
                    js_groups = clusters.get("job_search_status", {}).get("groups", {})
                    for gid, gdata in js_groups.items():
                        if "актив" in (gdata.get("title", "")).lower() or gid == "active_search":
                            active_seekers = gdata.get("count", 0)
                            break
                    skill_groups = clusters.get("skill", {}).get("groups", {})
                    sorted_skills = sorted(skill_groups.items(), key=lambda x: x[1].get("count", 0), reverse=True)
                    for gid, gdata in sorted_skills[:20]:
                        top_competitor_skills.append({
                            "name": gdata.get("title", gid),
                            "count": gdata.get("count", 0),
                        })
                except (json.JSONDecodeError, KeyError) as e:
                    log_debug(f"_analyze_resume clusters parse error: {e}")

            vacancy_count = 0
            try:
                r_vac = requests.get(
                    f"{hh_base()}/search/vacancy?text={encoded_title}&area=1",
                    headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml"},
                    cookies=cookies, timeout=10,
                )
                if r_vac.status_code == 200:
                    vac_ssr = parse_hh_lux_ssr(r_vac.text)
                    sc = vac_ssr.get("searchCounts", {})
                    if isinstance(sc, dict) and sc.get("value"):
                        vacancy_count = int(sc["value"])
                    if not vacancy_count:
                        for ssr_key in ("totalVacancies", "vacancyCount"):
                            v = vac_ssr.get(ssr_key)
                            if v:
                                vacancy_count = int(v)
                                break
                    if not vacancy_count:
                        vsr = vac_ssr.get("vacancySearchResult", {})
                        vacancy_count = int(vsr.get("found", 0) or vsr.get("total", 0) or 0)
                    if not vacancy_count:
                        for pattern in [
                            r'data-qa="vacancies-total-found"[^>]*>\s*([\d\s\xa0]+)',
                            r'"found"\s*:\s*(\d+)',
                            r'Найден\w*\s+([\d\s\xa0]+)\s+ваканс',
                        ]:
                            m_found = re.search(pattern, r_vac.text)
                            if m_found:
                                vacancy_count = int(m_found.group(1).replace(" ", "").replace("\xa0", ""))
                                break
            except Exception as e:
                log_debug(f"_analyze_resume supply_demand error: {e}")

            supply_demand = round(active_seekers / vacancy_count, 2) if vacancy_count > 0 else 0

            market = {
                "search_term": search_term,
                "vacancy_count": vacancy_count,
                "active_seekers": active_seekers,
                "supply_demand_ratio": supply_demand,
                "experience_distribution": experience_dist,
                "top_competitor_skills": top_competitor_skills,
            }
        except Exception as e:
            log_debug(f"_analyze_resume market analysis error: {e}")

        # 5. Field weight analysis — exact recipe for 100%
        weight_analysis = []
        _FIELD_LABELS = {
            "experience": "Опыт работы", "keySkills": "Ключевые навыки", "advancedKeySkills": "Навыки (расширенные)",
            "primaryEducation": "Образование", "title": "Должность", "professionalRole": "Проф. роль",
            "area": "Город", "phone": "Телефон", "language": "Языки", "firstName": "Имя", "lastName": "Фамилия",
            "photo": "Фото", "salary": "Зарплата", "email": "Email", "recommendation": "Рекомендации",
            "personalSite": "Сайт/портфолио", "additionalEducation": "Курсы", "attestationEducation": "Экзамены",
            "middleName": "Отчество", "portfolio": "Портфолио", "metro": "Метро", "skills": "О себе",
            "certificate": "Сертификаты", "driverLicenseTypes": "Водительские права", "hasVehicle": "Автомобиль",
        }
        conds = resume.get("_conditions", {})
        total_weight = 0
        filled_weight = 0
        for field, info in conds.items():
            if not isinstance(info, dict):
                continue
            w = info.get("weight", 0)
            st = info.get("status", "")
            if w > 0:
                total_weight += w
                is_filled = st not in ("green", "inactive", "")
                if is_filled:
                    filled_weight += w
                weight_analysis.append({
                    "field": field,
                    "label": _FIELD_LABELS.get(field, field),
                    "weight": w,
                    "filled": is_filled,
                    "status": st,
                })
        weight_analysis.sort(key=lambda x: (-1 if not x["filled"] else 1, -x["weight"]))

        # 6. Supply/demand across multiple search terms
        supply_demand_comparison = []
        try:
            terms = set()
            if title:
                for part in title.split(","):
                    t = part.strip()
                    if t and len(t) > 3:
                        terms.add(t)
            for r in roles:
                if r:
                    terms.add(r)
            if any("тестир" in t.lower() or "qa" in t.lower() for t in terms):
                terms.update(["автоматизация тестирования", "QA engineer"])
            if extra_terms:
                terms.update(extra_terms)

            for term in list(terms)[:10]:
                try:
                    enc = urllib.parse.quote(term)
                    r_vc = requests.get(
                        f"{hh_base()}/search/vacancy?text={enc}&area=1",
                        headers={"User-Agent": ua, "Accept": "text/html"},
                        cookies=cookies, timeout=10,
                    )
                    vc = 0
                    if r_vc.status_code == 200:
                        vc_ssr = parse_hh_lux_ssr(r_vc.text)
                        sc = vc_ssr.get("searchCounts", {})
                        if isinstance(sc, dict) and sc.get("value"):
                            vc = int(sc["value"])
                        if not vc:
                            m_f = re.search(r'"found"\s*:\s*(\d+)', r_vc.text[:5000])
                            if m_f:
                                vc = int(m_f.group(1))
                    supply_demand_comparison.append({
                        "term": term,
                        "vacancies": vc,
                        "ratio": round(active_seekers / vc, 1) if vc > 0 else 0,
                    })
                except Exception as e:
                    log_debug(f"_analyze_resume term={term!r}: {e}")
            supply_demand_comparison.sort(key=lambda x: x.get("ratio") or 9999)
        except Exception as e:
            log_debug(f"_analyze_resume supply/demand comparison error: {e}")

        # 7. HR activity analysis
        hr_activity = {"active_count": 0, "slow_count": 0, "dead_count": 0}
        try:
            r_neg = requests.get(
                hh_base() + "/applicant/negotiations",
                headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml"},
                cookies=cookies, timeout=15,
            )
            if r_neg.status_code == 200 and not _is_login_page(r_neg.text):
                neg_ssr = parse_hh_lux_ssr(r_neg.text)
                managers = neg_ssr.get("applicantEmployerManagersActivity", [])
                if isinstance(managers, list):
                    for mgr in managers:
                        if not isinstance(mgr, dict):
                            continue
                        inactive_min = mgr.get("@inactiveMinutes", mgr.get("inactiveMinutes", 0))
                        if not isinstance(inactive_min, (int, float)):
                            try:
                                inactive_min = int(inactive_min)
                            except (ValueError, TypeError) as e:
                                log_debug(f"_analyze_resume inactive_min parse error: {e}")
                                inactive_min = 0
                        inactive_days = inactive_min / 1440.0
                        if inactive_days < 3:
                            hr_activity["active_count"] += 1
                        elif inactive_days <= 7:
                            hr_activity["slow_count"] += 1
                        else:
                            hr_activity["dead_count"] += 1
        except Exception as e:
            log_debug(f"_analyze_resume hr_activity error: {e}")

        return {
            "ok": True,
            "name": f"{_str(resume.get('firstName'))} {_str(resume.get('lastName'))}".strip(),
            "title": title,
            "roles": roles,
            "skills": skills[:25],
            "total_experience_months": int(_str(resume.get("totalExperience")) or 0),
            "education_level": _str(resume.get("educationLevel")),
            "percent": percent,
            "status": status,
            "job_search_status": job_status,
            "job_search_status_label": _STATUS_MAP.get(job_status, job_status),
            "salary": salary_str,
            "work_schedule": [_SCHEDULE_MAP.get(s, s) for s in work_schedule],
            "work_formats": [_FORMAT_MAP.get(s, s) for s in work_formats],
            "employment": [_EMPLOY_MAP.get(s, s) for s in employment],
            "has_photo": "photo" not in green,
            "area": _str(resume.get("area")),
            "stats_7d": {
                "search_shows": search_shows,
                "views": views,
                "views_new": views_new,
                "invitations": invitations,
                "invitations_new": inv_new,
            },
            "issues": issues,
            "green_fields": green,
            "market": market,
            "weight_analysis": weight_analysis,
            "filled_weight": filled_weight,
            "total_weight": total_weight,
            "supply_demand_comparison": supply_demand_comparison,
            "hr_activity": hr_activity,
        }
    except Exception as e:
        log_debug(f"_analyze_resume error: {e}")
        return {"error": str(e)}


def _edit_resume_field(acc: dict, resume_hash: str, fields: dict) -> dict:
    """Edit resume fields via POST /applicant/resume/edit. Returns {ok, error}."""
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    try:
        # Warm up session (DDoS Guard needs a GET first)
        s = requests.Session()
        s.verify = False
        try:
            s.get(hh_base() + "/applicant/resumes", headers={"User-Agent": ua, "Accept": "text/html"},
                  cookies=acc.get("cookies", {}), timeout=10)
            # POST edit
            r = s.post(
            f"{hh_base()}/applicant/resume/edit?resume={resume_hash}&hhtmSource=resume_partial_edit",
            headers={
                "User-Agent": ua,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Xsrftoken": xsrf,
                "Origin": "https://hh.ru",
                "Referer": f"{hh_base()}/resume/edit/{resume_hash}/position",
            },
            cookies=acc.get("cookies", {}),
            json=fields,
            timeout=15,
        )
            if r.status_code in (200, 204):
                return {"ok": True}
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        finally:
            s.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Job-search status (/shards/user_statuses/job_search_status) ────────
# Узнали реверсом chatik-чанков App.70eb24dc02eddc32.js: PUT с query
# ?status=<value>, body пустой. GET → 405. Только PUT.

_JOB_SEARCH_STATUSES = {
    "active_search":        "🟢 Активно ищу работу",
    "looking_for_offers":   "🟡 Рассматриваю предложения",
    "accept_offers":        "🟡 Готова к предложениям",
    "has_job_offer":        "🟠 Есть оффер",
    "accepted_job_offer":   "🔵 Принят оффер",
    "not_looking_for_job":  "🔴 Не ищу работу",
}


def set_job_search_status(acc: dict, status: str) -> dict:
    """PUT /shards/user_statuses/job_search_status?status=<...>.
    Возвращает {ok: bool, status: <new>, error?: str}.
    """
    status = (status or "").strip().lower()
    if status not in _JOB_SEARCH_STATUSES:
        return {"ok": False, "error": f"Неизвестный статус: {status!r}. Доступные: {list(_JOB_SEARCH_STATUSES)}"}
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"
    xsrf = (acc.get("cookies") or {}).get("_xsrf", "")
    try:
        r = requests.put(
            f"{hh_base()}/shards/user_statuses/job_search_status",
            params={"status": status},
            cookies=acc.get("cookies") or {},
            headers={
                "User-Agent": ua,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-XSRFToken": xsrf,
                "Origin": hh_base(),
                "Referer": f"{hh_base()}/applicant/resumes",
            },
            timeout=10,
        )
        if r.status_code in (200, 204):
            return {"ok": True, "status": status, "label": _JOB_SEARCH_STATUSES[status]}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def fetch_account_diagnostics(acc: dict) -> dict:
    """Прогнать «диагностику аккаунта» через SSR /applicant/resumes.
    Возвращает {status: str|None, red_flags: [str], stats: {...}, resumes: [{...}]}
    red_flags — список понятных строк, которые надо показать юзеру.
    """
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"
    out = {"status": None, "status_label": None, "red_flags": [], "stats": {}, "resumes": []}
    try:
        r = requests.get(
            f"{hh_base()}/applicant/resumes",
            cookies=acc.get("cookies") or {},
            headers={"User-Agent": ua, "Accept": "text/html", "Referer": f"{hh_base()}/"},
            timeout=15, allow_redirects=True,
        )
        if r.status_code != 200 or _is_login_page(r.text):
            out["red_flags"].append("⚠️ Куки протухли — не удалось загрузить /applicant/resumes")
            return out
        ssr = parse_hh_lux_ssr(r.text)
        if not ssr:
            out["red_flags"].append("⚠️ SSR-стейт не нашли — может HH обновил вёрстку")
            return out
    except Exception as e:
        out["red_flags"].append(f"⚠️ Ошибка загрузки: {e}")
        return out

    # 1) jobSearchStatus
    aus = (ssr.get("applicantUserStatuses") or {}).get("jobSearchStatus") or {}
    name = (aus.get("name") or "").lower()
    out["status"] = name
    out["status_label"] = _JOB_SEARCH_STATUSES.get(name, name)
    if name == "not_looking_for_job":
        out["red_flags"].append("🚨 Статус «Не ищу работу» — HR видят бейдж, % ответов падает. Переключи на «active_search».")
    elif name not in ("active_search", "looking_for_offers", "accept_offers"):
        out["red_flags"].append(f"⚠️ Статус «{name}» — лучше переключить на active_search или looking_for_offers")

    # 2) Resumes
    for res in (ssr.get("applicantResumes") or []):
        attrs = res.get("_attributes") or {}
        title = _hh_ssr_str(res.get("title")) or "(без названия)"
        rh = res.get("hash") or attrs.get("hash") or ""
        rd = {
            "title": title,
            "hash": rh,
            "canTouch": attrs.get("canTouch", True),
            "canPublishOrUpdate": attrs.get("canPublishOrUpdate", True),
            "hasPublicVisibility": attrs.get("hasPublicVisibility", True),
            "hasErrors": attrs.get("hasErrors", False),
            "hasConditions": attrs.get("hasConditions", False),
            "accessType": _hh_ssr_str(res.get("accessType")) or "",
        }
        out["resumes"].append(rd)
        prefix = f"📄 [{title[:30]}]"
        # hasPublicVisibility=false означает только «не индексируется в гугле без логина»,
        # внутри HH резюме всё равно видно HR-клиентам с подпиской.
        # Реально проблемно только accessType=no_one (скрыто ото всех).
        if rd["accessType"] == "no_one":
            out["red_flags"].append(f"🚨 {prefix} accessType=no_one — резюме скрыто от ВСЕХ работодателей")
        if rd["hasErrors"]:
            out["red_flags"].append(f"⚠️ {prefix} hasErrors=True — есть ошибки в полях")
        if rd["accessType"] not in ("clients", "whitelist", "blacklist", "direct", "direct_url", "no_one", ""):
            out["red_flags"].append(f"⚠️ {prefix} accessType={rd['accessType']} — нестандартный режим видимости")

    # 3) Stats
    stats_raw = (ssr.get("applicantResumesStatistics") or {}).get("resumes") or {}
    out["stats"]["per_resume"] = {}
    for rh, info in stats_raw.items():
        s = info.get("statistics") or {}
        out["stats"]["per_resume"][rh] = {
            "search_shows": (s.get("searchShows") or {}).get("count", 0),
            "views":        (s.get("views") or {}).get("count", 0),
            "views_new":    (s.get("views") or {}).get("countNew", 0),
            "invitations":  (s.get("invitations") or {}).get("count", 0),
            "invites_new":  (s.get("invitations") or {}).get("countNew", 0),
            "period_days":  s.get("periodDays", 7),
            "recommendation": info.get("recommendation", ""),
        }
    out["stats"]["resume_limits"] = ssr.get("resumeLimits") or {}
    out["stats"]["suitable_vacancies"] = ssr.get("applicantSuitableVacancyByResume") or {}
    out["stats"]["user_stats"] = ssr.get("userStats") or {}
    out["stats"]["global_invitations"] = ssr.get("globalInvitations")
    return out
