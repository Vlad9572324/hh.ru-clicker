"""
HH.ru API helper functions: headers, parsing IDs, vacancy metadata, salaries, schedules.
"""

import re
import urllib.parse

from bs4 import BeautifulSoup

from app.logging_utils import log_debug
from app.config import CONFIG


def get_headers(xsrf: str) -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://hh.ru",
        "X-XsrfToken": xsrf
    }


# Single-entry cache so that the 4 thin wrappers share one BeautifulSoup parse
# when called sequentially with the same html string (typical caller pattern).
_last_html_ref = None
_last_parsed_result = None


def parse_search_page(html: str) -> dict:
    """Один BeautifulSoup parse → {ids, meta, salaries, schedules}."""
    global _last_html_ref, _last_parsed_result
    if html is _last_html_ref and _last_parsed_result is not None:
        return _last_parsed_result

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        log_debug(f"parse_search_page: BeautifulSoup failed: {e}")
        return {"ids": set(), "meta": {}, "salaries": {}, "schedules": {}}

    # ---- IDs ---------------------------------------------------------------
    ids = set()
    for link in soup.find_all("a", href=re.compile(r"/vacancy/\d+")):
        m = re.search(r"/vacancy/(\d+)", link["href"])
        if m:
            ids.add(m.group(1))

    # ---- Meta --------------------------------------------------------------
    meta = {}
    for item in soup.find_all(attrs={"data-qa": re.compile(r"vacancy-serp__vacancy$")}):
        title_el = item.find("a", attrs={"data-qa": re.compile(r"serp-item__title|vacancy-serp__vacancy-title")})
        if not title_el:
            title_el = item.find("a", href=re.compile(r"/vacancy/\d+"))
        if not title_el:
            continue
        m = re.search(r"/vacancy/(\d+)", title_el.get("href", ""))
        if not m:
            continue
        vid = m.group(1)
        title = title_el.get_text(strip=True)
        company = ""
        comp_el = item.find(attrs={"data-qa": re.compile(r"vacancy-serp__vacancy-employer")})
        if comp_el:
            company = comp_el.get_text(strip=True)
        if title:
            meta[vid] = {"title": title, "company": company}

    if not meta:
        for link in soup.find_all("a", href=re.compile(r"/vacancy/\d+")):
            m = re.search(r"/vacancy/(\d+)", link.get("href", ""))
            if not m:
                continue
            vid = m.group(1)
            if vid in meta:
                continue
            title = link.get_text(strip=True)
            if title and len(title) > 4:
                meta[vid] = {"title": title, "company": ""}

    # ---- Salaries ----------------------------------------------------------
    salaries = {}
    # Safer regex: avoids catastrophic backtracking on nested braces.
    for m in re.finditer(r'"(?:compensation|salary)"\s*:\s*\{((?:[^{}]|\{[^{}]*\})*)\}', html):
        comp_str = m.group(1)
        if '"noCompensation"' in comp_str or '"from"' not in comp_str:
            continue
        from_m = re.search(r'"from"\s*:\s*(\d+)', comp_str)
        if not from_m:
            continue

        context = html[max(0, m.start() - 2000): m.start()]
        vid_matches = re.findall(r'/vacancy/(\d+)', context)
        if not vid_matches:
            continue
        vid = vid_matches[-1]

        salary = int(from_m.group(1))
        curr_m = re.search(r'"currencyCode"\s*:\s*"(\w+)"', comp_str)
        curr = curr_m.group(1) if curr_m else "RUR"
        if curr == "USD":
            salary = salary * 90
        elif curr == "EUR":
            salary = salary * 100
        salaries[vid] = salary

    # ---- Schedules ---------------------------------------------------------
    schedules = {}
    for m in re.finditer(r'"(?:workSchedule(?:Type)?s?|scheduleType(?:Name)?s?)"\s*:\s*\[([^\]]{0,500})\]', html):
        block = m.group(1)
        context = html[max(0, m.start() - 2000): m.start()]
        vid_matches = re.findall(r'/vacancy/(\d+)', context)
        if not vid_matches:
            continue
        vid = vid_matches[-1]
        if vid not in schedules:
            schedules[vid] = set()
        for sid in re.findall(r'"id"\s*:\s*"(\w+)"', block):
            schedules[vid].add(sid)
        for label in re.findall(r'"([^"]+)"', block):
            label_lower = label.lower().strip()
            for key, code in _SCHEDULE_LABELS.items():
                if key in label_lower:
                    schedules[vid].add(code)
                    break

    for m in re.finditer(r'data-qa="[^"]*(?:schedule|work-mode|work-format)[^"]*"[^>]*>([^<]{2,50})<', html):
        label = m.group(1).strip().lower()
        context = html[max(0, m.start() - 3000): m.start()]
        vid_matches = re.findall(r'/vacancy/(\d+)', context)
        if not vid_matches:
            continue
        vid = vid_matches[-1]
        if vid not in schedules:
            schedules[vid] = set()
        for key, code in _SCHEDULE_LABELS.items():
            if key in label:
                schedules[vid].add(code)
                break

    result = {"ids": ids, "meta": meta, "salaries": salaries, "schedules": schedules}
    _last_html_ref = html
    _last_parsed_result = result
    return result


def parse_ids(html: str) -> set:
    result = parse_search_page(html)["ids"]
    log_debug(f"🔍 Парсинг: найдено {len(result)} вакансий")
    return result


def parse_vacancy_meta(html: str) -> dict:
    """
    Из HTML страницы поиска извлекает {vacancy_id: {title, company}}.
    Используется как fallback когда API-ответ не содержит shortVacancy.
    """
    return parse_search_page(html)["meta"]


def parse_salaries(html: str, ids: set) -> dict:
    """
    Извлекает зарплату (from, в рублях) для вакансий из HTML поисковой выдачи.
    Возвращает {vacancy_id: salary_from_rub_or_None}.
    Работает только если CONFIG.min_salary > 0 (иначе пустой результат).
    """
    result = {vid: None for vid in ids}
    if not ids or not CONFIG.min_salary:
        return result
    all_salaries = parse_search_page(html)["salaries"]
    for vid in ids:
        if vid in all_salaries:
            result[vid] = all_salaries[vid]
    return result


_SCHEDULE_LABELS = {
    "удалённая": "remote", "удаленная": "remote", "remote": "remote",
    "полный день": "fullDay", "full day": "fullDay", "fullday": "fullDay",
    "гибкий": "flexible", "flexible": "flexible",
    "сменный": "shift", "shift": "shift",
    "вахтовый": "flyInFlyOut", "flyinflyout": "flyInFlyOut", "вахта": "flyInFlyOut",
}


def parse_work_schedules(html: str, ids: set) -> dict:
    """
    Извлекает формат работы для вакансий из HTML поисковой выдачи.
    Возвращает {vacancy_id: set_of_schedule_ids} (e.g. {"remote", "flexible"}).
    """
    result = {vid: set() for vid in ids}
    if not ids or not CONFIG.allowed_schedules:
        return result
    all_schedules = parse_search_page(html)["schedules"]
    for vid in ids:
        if vid in all_schedules:
            result[vid] = all_schedules[vid]
    return result


def extract_search_query(url: str) -> str:
    """Извлекает поисковый запрос из URL"""
    if "text=" in url:
        match = re.search(r"text=([^&]+)", url)
        if match:
            return urllib.parse.unquote_plus(match.group(1))
    if "resume=" in url:
        return "По резюме"
    return "Поиск"


def parse_apply_strategy_meta(html: str) -> dict:
    """Из SSR JSON поисковой выдачи достаём apply-стратегические поля по
    каждой вакансии: {vacancy_id: {accept_auto_response, chat_write_possibility, hr_online}}.

    Парсится из <template id="HH-Lux-InitialState">…vacancySearchResult.vacancies[]…</template>.
    Эти поля HH отдает только в списке (на странице /vacancy/{vid} они null),
    так что собираем когда чанк уже загружен — без дополнительных fetch'ей.
    """
    from app.hh_resume import parse_hh_lux_ssr
    out: dict[str, dict] = {}
    try:
        ssr = parse_hh_lux_ssr(html)
        if not isinstance(ssr, dict):
            return out
        vsr = ssr.get("vacancySearchResult") or ssr.get("relatedVacancies") or {}
        vacs = vsr.get("vacancies") or []
        labels_map = ssr.get("userLabelsForVacancies") or {}

        def _lab_for(vid_str):
            labs = labels_map.get(vid_str)
            if labs is None and vid_str.isdigit():
                labs = labels_map.get(int(vid_str))
            if not isinstance(labs, list):
                return []
            return [str(l) for l in labs if isinstance(l, str)]

        for v in vacs:
            if not isinstance(v, dict):
                continue
            vid = v.get("vacancyId") or v.get("id")
            if not vid:
                continue
            vid = str(vid)
            ar = (v.get("autoResponse") or {})
            em = (v.get("employerManager") or {})
            out[vid] = {
                "accept_auto_response": bool(ar.get("acceptAutoResponse")) if "acceptAutoResponse" in ar else None,
                "chat_write_possibility": v.get("chatWritePossibility", ""),
                "response_letter_required": v.get("@responseLetterRequired"),
                "hr_online": em.get("latestActivity", ""),
                "hh_labels": _lab_for(vid),
            }
        # Также для вакансий с labels, но без полной meta (не в vacancies[]) —
        # хотя бы labels сохраним: DISCARD-фильтр пригодится по всем известным id.
        for vid_raw, labs in labels_map.items():
            vid_s = str(vid_raw)
            if vid_s in out:
                continue
            normalized = [str(l) for l in (labs or []) if isinstance(l, str)]
            if normalized:
                out[vid_s] = {"hh_labels": normalized}
    except Exception as e:
        log_debug(f"parse_apply_strategy_meta error: {e}")
    return out
