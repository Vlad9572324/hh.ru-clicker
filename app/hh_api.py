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


def parse_ids(html: str) -> set:
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        log_debug(f"parse_ids: BeautifulSoup failed: {e}")
        return set()
    ids = set()
    for link in soup.find_all("a", href=re.compile(r"/vacancy/\d+")):
        m = re.search(r"/vacancy/(\d+)", link["href"])
        if m:
            ids.add(m.group(1))
    log_debug(f"🔍 Парсинг: найдено {len(ids)} вакансий")
    return ids


def parse_vacancy_meta(html: str) -> dict:
    """
    Из HTML страницы поиска извлекает {vacancy_id: {title, company}}.
    Используется как fallback когда API-ответ не содержит shortVacancy.
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    # Основной путь: ищем элементы вакансий по data-qa
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
            result[vid] = {"title": title, "company": company}

    # Fallback: любая ссылка на вакансию с непустым текстом
    if not result:
        for link in soup.find_all("a", href=re.compile(r"/vacancy/\d+")):
            m = re.search(r"/vacancy/(\d+)", link.get("href", ""))
            if not m:
                continue
            vid = m.group(1)
            if vid in result:
                continue
            title = link.get_text(strip=True)
            if title and len(title) > 4:
                result[vid] = {"title": title, "company": ""}

    return result


def parse_salaries(html: str, ids: set) -> dict:
    """
    Извлекает зарплату (from, в рублях) для вакансий из HTML поисковой выдачи.
    Возвращает {vacancy_id: salary_from_rub_or_None}.
    Работает только если CONFIG.min_salary > 0 (иначе пустой результат).
    """
    result = {vid: None for vid in ids}
    if not ids or not CONFIG.min_salary:
        return result

    # Ищем все блоки compensation/salary в HTML и смотрим какая вакансия была упомянута
    # ближайшей по тексту перед каждым блоком
    for m in re.finditer(r'"(?:compensation|salary)"\s*:\s*\{([^}]{0,1500})\}', html):
        comp_str = m.group(1)
        if '"noCompensation"' in comp_str or '"from"' not in comp_str:
            continue
        from_m = re.search(r'"from"\s*:\s*(\d+)', comp_str)
        if not from_m:
            continue

        # Ищем последний упомянутый vacancy ID в 2000 символах перед этим блоком
        context = html[max(0, m.start() - 2000): m.start()]
        vid_matches = re.findall(r'/vacancy/(\d+)', context)
        if not vid_matches:
            continue
        vid = vid_matches[-1]
        if vid not in result or result[vid] is not None:
            continue

        salary = int(from_m.group(1))
        curr_m = re.search(r'"currencyCode"\s*:\s*"(\w+)"', comp_str)
        curr = curr_m.group(1) if curr_m else "RUR"
        if curr == "USD":
            salary = salary * 90
        elif curr == "EUR":
            salary = salary * 100
        result[vid] = salary

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

    # Approach 1: JSON — ищем "workSchedules":[{"id":"remote"}] или "scheduleTypeNames":["Удалённая"]
    for m in re.finditer(r'"(?:workSchedule(?:Type)?s?|scheduleType(?:Name)?s?)"\s*:\s*\[([^\]]{0,500})\]', html):
        block = m.group(1)
        # Ищем ближайший vacancy ID перед этим блоком
        context = html[max(0, m.start() - 2000): m.start()]
        vid_matches = re.findall(r'/vacancy/(\d+)', context)
        if not vid_matches:
            continue
        vid = vid_matches[-1]
        if vid not in result:
            continue
        # Извлекаем id из JSON-объектов {"id":"remote"} или строк "Удалённая работа"
        for sid in re.findall(r'"id"\s*:\s*"(\w+)"', block):
            result[vid].add(sid)
        for label in re.findall(r'"([^"]+)"', block):
            label_lower = label.lower().strip()
            for key, code in _SCHEDULE_LABELS.items():
                if key in label_lower:
                    result[vid].add(code)
                    break

    # Approach 2: HTML labels — data-qa элементы с расписанием
    for m in re.finditer(r'data-qa="[^"]*(?:schedule|work-mode|work-format)[^"]*"[^>]*>([^<]{2,50})<', html):
        label = m.group(1).strip().lower()
        context = html[max(0, m.start() - 3000): m.start()]
        vid_matches = re.findall(r'/vacancy/(\d+)', context)
        if not vid_matches:
            continue
        vid = vid_matches[-1]
        if vid not in result:
            continue
        for key, code in _SCHEDULE_LABELS.items():
            if key in label:
                result[vid].add(code)
                break

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
