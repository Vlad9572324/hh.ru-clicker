"""HH.ru HTTP, parsing, questionnaire, resume, and LLM helpers."""

import aiohttp
import asyncio
import json
import random
import re
import ssl
import time
import urllib.parse
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from glom import glom

try:
    import openai as _openai_mod
    _openai_available = True
except ImportError:
    _openai_available = False

from .state import CONFIG, _url_entry, _url_pages_map
from .storage import (
    add_test_vacancy,
    log_debug,
    record_answer_history,
    upsert_interview,
)

_llm_rr_index = 0
_resume_cache: dict = {}
_RESUME_CACHE_TTL = 4 * 3600

def _is_login_page(html: str) -> bool:
    """Определить, является ли HTML страница страницей входа HH (протухшие куки)."""
    if not html:
        return False
    return (
        '"/account/login"' in html
        or "hh.ru/account/login" in html
        or "Войти в аккаунт" in html
        or '"accountLogin"' in html
    )



def _url_entry(item) -> dict:
    """Нормализует элемент url_pool в {url, pages}."""
    if isinstance(item, str):
        return {"url": item.strip(), "pages": CONFIG.pages_per_url}
    return {"url": item.get("url", "").strip(), "pages": int(item.get("pages", CONFIG.pages_per_url))}


def _url_pages_map() -> dict:
    """Возвращает {url_str: pages} из CONFIG.url_pool."""
    return {e["url"]: e["pages"] for u in CONFIG.url_pool for e in [_url_entry(u)]}


# ============================================================
# API ФУНКЦИИ
# ============================================================

def get_headers(xsrf: str) -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://hh.ru",
        "X-XsrfToken": xsrf
    }


def parse_ids(html: str) -> set:
    soup = BeautifulSoup(html, "html.parser")
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

    # Запасной вариант: любая ссылка на вакансию с непустым текстом
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

    # Ищем все блоки compensation в HTML и смотрим какая вакансия была упомянута
    # ближайшей по тексту перед каждым блоком
    for m in re.finditer(r'"compensation"\s*:\s*\{([^}]{0,400})\}', html):
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


def extract_search_query(url: str) -> str:
    """Извлекает поисковый запрос из URL"""
    if "text=" in url:
        match = re.search(r"text=([^&]+)", url)
        if match:
            return urllib.parse.unquote_plus(match.group(1))
    if "resume=" in url:
        return "По резюме"
    return "Поиск"


async def fetch_page(session, url, sem):
    async with sem:
        try:
            await asyncio.sleep(0.05)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                html = await r.text()
                log_debug(f"✅ URL: {url} | Статус: {r.status} | Размер: {len(html)}")
                return html
        except Exception as e:
            log_debug(f"❌ ОШИБКА при загрузке: {url} | {type(e).__name__}: {e}")
            return ""


def get_questionnaire_answer(question_text: str) -> str:
    """Найти подходящий шаблонный ответ по ключевым словам вопроса."""
    matched = find_answer_template(question_text)
    if matched:
        return matched["answer"]
    return _fallback_answer()


def get_questionnaire_template_answer(question_text: str) -> str:
    """Return only a matched template answer; do not apply the default fallback."""
    matched = find_answer_template(question_text)
    return matched["answer"] if matched else ""


def find_answer_template(text: str) -> dict:
    """Return matched configured answer template or {} if no keywords match."""
    q_lower = (text or "").lower()
    for tmpl in CONFIG.questionnaire_templates:
        keywords = tmpl.get("keywords", [])
        answer = (tmpl.get("answer") or "").strip()
        if not keywords:
            continue
        if answer and any(str(kw).lower() in q_lower for kw in keywords if str(kw).strip()):
            return {
                "answer": answer,
                "template": tmpl,
                "matched_keywords": [kw for kw in keywords if str(kw).lower() in q_lower],
            }
    return {}


def _fallback_answer() -> str:
    return CONFIG.questionnaire_default_answer or "Готова рассказать подробнее на собеседовании."


def _llm_has_profile() -> bool:
    return bool(
        (CONFIG.llm_api_key or "").strip()
        or any(p.get("api_key") for p in (CONFIG.llm_profiles or []) if p.get("enabled", True))
    )


def _coerce_questionnaire_answer(q: dict, answer: str):
    """Convert a text answer into the exact HH form value for non-text fields."""
    answer = str(answer or "").strip()
    qtype = q.get("type", "textarea")
    options = q.get("options") or []
    if qtype == "textarea":
        return answer
    values = [str(o.get("value", "")) for o in options]
    if qtype == "radio":
        if answer in values:
            return answer
        lower = answer.lower()
        no_words = ("нет", "no", "не готов", "не готова", "не могу")
        if any(w in lower for w in no_words) and len(values) > 1:
            return values[1]
        return values[0] if values else answer
    if qtype == "checkbox":
        if answer in values:
            return answer
        return values[0] if values else answer
    return answer


def _build_vacancy_context(vacancy_title: str = "", company: str = "",
                           vacancy_data: dict = None) -> str:
    parts = []
    if vacancy_title:
        parts.append(f"Vacancy title: {vacancy_title}")
    if company:
        parts.append(f"Company: {company}")
    for k, v in (vacancy_data or {}).items():
        if v and k not in ("title", "company"):
            parts.append(f"{k}: {v}")
    return "\n".join(parts)


def _parse_questionnaire_fields(html: str) -> tuple:
    """
    Парсит форму опросника. Возвращает (questions, field_answers):
      questions: list of str (тексты вопросов по порядку)
      field_answers: dict {field_name: answer_value} — готовые значения для POST
    Поддерживает textarea, radio, checkbox.
    """
    # Тексты вопросов
    q_blocks = re.findall(
        r'data-qa="task-question">(.*?)(?=data-qa="task-question"|</(?:div|section|form)>)',
        html, re.DOTALL
    )
    questions = []
    for block in q_blocks:
        clean = re.sub(r'<[^>]+>', ' ', block)
        clean = re.sub(r'\s+', ' ', clean).strip()
        questions.append(clean)

    field_answers = {}

    # ── Textarea (task_*_text) ──────────────────────────────────
    for i, name in enumerate(re.findall(r'<textarea[^>]+name="(task_\d+_text)"', html)):
        q_text = questions[i] if i < len(questions) else ""
        field_answers[name] = get_questionnaire_template_answer(q_text)

    # ── Radio (task_*) ──────────────────────────────────────────
    # Собираем группы: {name: [(value, label), ...]}
    radio_groups: dict = {}
    for inp in re.findall(r'<input[^>]+type="radio"[^>]+>', html, re.IGNORECASE):
        name_m = re.search(r'name="([^"]+)"', inp)
        val_m  = re.search(r'value="([^"]+)"', inp)
        if name_m and val_m and re.match(r'task_\d+', name_m.group(1)):
            radio_groups.setdefault(name_m.group(1), []).append(val_m.group(1))

    # Для каждой radio-группы выбираем значение
    # Порядок radio-групп ≈ порядку вопросов после textarea
    textarea_count = len([k for k in field_answers])
    for i, (name, values) in enumerate(radio_groups.items()):
        if name in field_answers:
            continue
        q_idx = textarea_count + i
        q_text = questions[q_idx] if q_idx < len(questions) else ""
        tmpl_answer = get_questionnaire_template_answer(q_text).lower()

        chosen = values[0]  # дефолт — первый вариант

        # Ищем label-текст для каждого value чтобы сопоставить с шаблоном
        # Порядок: первый input = "да", второй = "нет" (типичная раскладка HH)
        # Если шаблон содержит "нет"/"no" — берём второй
        if any(w in tmpl_answer for w in ("нет", "no", "не готов", "не готова", "не могу")):
            chosen = values[1] if len(values) > 1 else values[0]

        field_answers[name] = chosen

    # ── Checkbox (task_*) ───────────────────────────────────────
    checkbox_groups: dict = {}
    for inp in re.findall(r'<input[^>]+type="checkbox"[^>]+>', html, re.IGNORECASE):
        name_m = re.search(r'name="([^"]+)"', inp)
        val_m  = re.search(r'value="([^"]+)"', inp)
        if name_m and val_m and re.match(r'task_\d+', name_m.group(1)):
            checkbox_groups.setdefault(name_m.group(1), []).append(val_m.group(1))

    for name, values in checkbox_groups.items():
        if name in field_answers:
            continue
        # Для чекбоксов выбираем первый вариант
        field_answers[name] = values[0]

    return questions, field_answers


def _parse_questionnaire_rich(html: str) -> list:
    """Парсит форму опросника и возвращает богатую структуру для LLM:
    list of {field, type, text, options: [{value, label}]}
    """
    q_blocks = re.findall(
        r'data-qa="task-question">(.*?)(?=data-qa="task-question"|</(?:div|section|form)>)',
        html, re.DOTALL
    )
    q_texts = []
    for b in q_blocks:
        c = re.sub(r'<[^>]+>', ' ', b)
        c = re.sub(r'&quot;', '"', re.sub(r'&ndash;', '–', re.sub(r'&nbsp;', ' ', c)))
        c = re.sub(r'\s+', ' ', c).strip()
        q_texts.append(c)

    result = []
    q_idx = 0

    for name in re.findall(r'<textarea[^>]+name="(task_\d+_text)"', html):
        result.append({"field": name, "type": "textarea",
                       "text": q_texts[q_idx] if q_idx < len(q_texts) else "", "options": []})
        q_idx += 1

    radio_groups: dict = {}
    radio_order: list = []
    for inp in re.findall(r'<input[^>]+type="radio"[^>]+>', html, re.I):
        nm = re.search(r'name="([^"]+)"', inp)
        vl = re.search(r'value="([^"]+)"', inp)
        if nm and vl and re.match(r'task_\d+', nm.group(1)):
            n, v = nm.group(1), vl.group(1)
            if n not in radio_groups:
                radio_groups[n] = []
                radio_order.append(n)
            radio_groups[n].append(v)

    label_map: dict = {}
    for inp_with_id in re.findall(r'<input[^>]+type="radio"[^>]+id="([^"]+)"[^>]*>', html, re.I):
        label_m = re.search(rf'<label[^>]+for="{re.escape(inp_with_id)}"[^>]*>(.*?)</label>', html, re.DOTALL)
        if label_m:
            lbl = re.sub(r'<[^>]+>', '', label_m.group(1)).strip()
            label_map[inp_with_id] = lbl
    default_labels = ["да", "нет"]

    for name in radio_order:
        vals = radio_groups[name]
        options = [{"value": v, "label": label_map.get(v, default_labels[i] if i < len(default_labels) else v)}
                   for i, v in enumerate(vals)]
        result.append({"field": name, "type": "radio",
                       "text": q_texts[q_idx] if q_idx < len(q_texts) else "", "options": options})
        q_idx += 1

    checkbox_groups: dict = {}
    checkbox_order: list = []
    for inp in re.findall(r'<input[^>]+type="checkbox"[^>]+>', html, re.I):
        nm = re.search(r'name="([^"]+)"', inp)
        vl = re.search(r'value="([^"]+)"', inp)
        if nm and vl and re.match(r'task_\d+', nm.group(1)):
            n, v = nm.group(1), vl.group(1)
            if n not in checkbox_groups:
                checkbox_groups[n] = []
                checkbox_order.append(n)
            checkbox_groups[n].append(v)

    for name in checkbox_order:
        vals = checkbox_groups[name]
        options = [{"value": v, "label": v} for v in vals]
        result.append({"field": name, "type": "checkbox",
                       "text": q_texts[q_idx] if q_idx < len(q_texts) else "", "options": options})
        q_idx += 1

    return result


async def fill_and_submit_questionnaire(acc: dict, vid: str,
                                        vacancy_title: str = "", company: str = "") -> tuple:
    """
    Получает страницу опроса, заполняет шаблонными ответами и отправляет.
    Поддерживает textarea, radio, checkbox.
    Возвращает (result, info): result = sent | limit | test | error
    """
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)

    headers_get = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"https://hh.ru/vacancy/{vid}",
    }

    try:
        async with aiohttp.ClientSession(
            cookies=acc["cookies"], connector=connector,
            headers=headers_get
        ) as session:
            url_form = f"https://hh.ru/applicant/vacancy_response?vacancyId={vid}&withoutTest=no"

            # Шаг 1: GET форма опроса
            async with session.get(url_form, timeout=aiohttp.ClientTimeout(total=15)) as r:
                html = await r.text()

            # Скрытые поля
            hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
            hidden.update(dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+type="hidden"[^>]+value="([^"]*)"', html)))

            # Парсим все поля опроса
            questions, field_answers = _parse_questionnaire_fields(html)
            rich_qs = _parse_questionnaire_rich(html)

            if not field_answers:
                log_debug(f"Questionnaire: no task fields found for {vid}")
                return "test", {}

            resume_text = fetch_resume_text(acc) if CONFIG.llm_use_resume else ""
            cover_letter = acc.get("letter", "") if CONFIG.llm_use_cover_letter else ""
            answer_decisions = resolve_questionnaire_answers(
                rich_qs, vacancy_title=vacancy_title, company=company,
                resume_text=resume_text, cover_letter=cover_letter,
            )
            for field, decision in answer_decisions.items():
                if field in field_answers:
                    field_answers[field] = decision["answer"]

            log_debug(f"Questionnaire {vid}: {len(field_answers)} fields, {len(questions)} questions")
            for name, val in field_answers.items():
                log_debug(f"  {name} = {str(val)[:80]}")
                d = answer_decisions.get(name, {})
                record_answer_history(
                    kind="questionnaire",
                    source=d.get("source", "fallback"),
                    question=d.get("question", name),
                    answer=str(val),
                    account=acc.get("name", ""),
                    vacancy_id=vid,
                    vacancy_title=vacancy_title,
                    company=company,
                    metadata={**(d.get("metadata") or {}), "field": name, "raw_answer": d.get("raw_answer", "")},
                )

            # Шаг 2: POST данные
            data = aiohttp.FormData()
            data.add_field("resume_hash", acc["resume_hash"])
            data.add_field("vacancy_id", vid)
            data.add_field("letter", acc["letter"])
            data.add_field("lux", "true")

            for name in ("_xsrf", "uidPk", "guid", "startTime", "testRequired"):
                if name in hidden:
                    data.add_field(name, hidden[name])

            for name, value in field_answers.items():
                data.add_field(name, str(value))

            # Шаг 3: POST
            async with session.post(
                url_form,
                headers={"X-Xsrftoken": acc["cookies"]["_xsrf"], "Referer": url_form},
                data=data,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False,
            ) as r2:
                status = r2.status
                location = r2.headers.get("location", "")
                txt = await r2.text()

            log_debug(f"Questionnaire submit {vid}: HTTP {status} location={location}")

            if status in (302, 303):
                if "negotiations-limit-exceeded" in location or "negotiations-limit-exceeded" in txt:
                    return "limit", {}
                # Редирект назад на форму — ошибка валидации
                if "withoutTest=no" in location or f"vacancyId={vid}" in location:
                    log_debug(f"Questionnaire {vid}: form rejected, redirect back")
                    return "test", {}
                return "sent", {"answer_sources": {k: v.get("source") for k, v in answer_decisions.items()}}

            if status == 200:
                if "negotiations-limit-exceeded" in txt:
                    return "limit", {}
                if "test-required" in txt:
                    return "test", {}
                return "sent", {"answer_sources": {k: v.get("source") for k, v in answer_decisions.items()}}

            return "test", {}

    except Exception as e:
        log_debug(f"fill_and_submit_questionnaire error: {e}")
        return "error", {"exception": str(e)}


async def send_response_async(acc: dict, vid: str) -> tuple:
    """Асинхронная отправка отклика. Возвращает (результат, инфо)"""
    log_debug(f"📤 ОТПРАВКА ОТКЛИКА на вакансию {vid} | Аккаунт: {acc['name']}")

    headers = get_headers(acc["cookies"]["_xsrf"])

    data = aiohttp.FormData()
    data.add_field("resume_hash", acc["resume_hash"])
    data.add_field("vacancy_id", vid)
    data.add_field("letterRequired", "true")
    data.add_field("letter", acc["letter"])
    data.add_field("lux", "true")
    data.add_field("ignore_postponed", "true")

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    connector = aiohttp.TCPConnector(ssl=ssl_context)

    try:
        async with aiohttp.ClientSession(headers=headers, cookies=acc["cookies"], connector=connector) as session:
            async with session.post(
                "https://hh.ru/applicant/vacancy_response/popup",
                data=data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                txt = await r.text()
                status_code = r.status

        log_debug(f"   Ответ HTTP: {status_code} | Размер: {len(txt)}")

        if status_code in (401, 403):
            return "auth_error", {}

        if status_code == 200 and _is_login_page(txt):
            return "auth_error", {}

        if status_code == 200:
            if "shortVacancy" in txt:
                try:
                    p = json.loads(txt)
                    info = {
                        "title": glom(p, "responseStatus.shortVacancy.name", default="?"),
                        "company": glom(p, "responseStatus.shortVacancy.company.name", default="?"),
                        "salary_from": glom(p, "responseStatus.shortVacancy.compensation.from", default=None),
                        "salary_to": glom(p, "responseStatus.shortVacancy.compensation.to", default=None),
                    }
                    return "sent", info
                except Exception as e:
                    return "sent", {}

            if '"success":true' in txt or '"status":"ok"' in txt or '"responded":true' in txt:
                return "sent", {}

            return "sent", {}

        if "negotiations-limit-exceeded" in txt:
            return "limit", {}

        if "test-required" in txt:
            info = {}
            if "shortVacancy" in txt:
                try:
                    p = json.loads(txt)
                    info = {
                        "title": glom(p, "responseStatus.shortVacancy.name", default=""),
                        "company": glom(p, "responseStatus.shortVacancy.company.name", default=""),
                    }
                except:
                    pass
            return "test", info

        if "alreadyApplied" in txt:
            return "already", {}

        return "error", {"raw": txt[:200]}
    except Exception as e:
        return "error", {"exception": str(e)}


def check_limit(acc: dict) -> bool:
    """True если лимит активен"""
    headers = get_headers(acc["cookies"]["_xsrf"])
    try:
        r = requests.post(
            "https://hh.ru/applicant/vacancy_response/popup",
            headers=headers, cookies=acc["cookies"],
            files={"resume_hash": (None, acc["resume_hash"]), "vacancy_id": (None, "1")},
            timeout=10
        )
        return "negotiations-limit-exceeded" in r.text
    except:
        return True


def touch_resume(acc: dict) -> tuple:
    """
    Поднять резюме в поиске.
    Возвращает (success: bool, message: str)
    """
    headers = get_headers(acc["cookies"]["_xsrf"])
    resume_hash = acc["resume_hash"]

    touch_files = {
        "resume": (None, resume_hash),
        "undirectable": (None, "true")
    }

    try:
        response = requests.post(
            "https://hh.ru/applicant/resumes/touch",
            headers=headers,
            cookies=acc["cookies"],
            files=touch_files,
            timeout=10
        )

        if response.status_code == 200:
            return True, "Резюме поднято!"
        elif response.status_code == 429:
            return False, "Слишком часто (429)"
        else:
            return False, f"HTTP {response.status_code}"

    except Exception as e:
        return False, f"Ошибка: {str(e)[:30]}"


def fetch_hh_negotiations_stats(acc: dict, max_pages: int = 20) -> dict:
    """Получить статистику откликов с hh.ru (парсинг HTML)"""
    cookies = acc["cookies"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://hh.ru/applicant/negotiations",
    }

    result = {
        "interview": 0,
        "recent_interview": 0,  # только последние 60 дней
        "viewed": 0,
        "not_viewed": 0,
        "discard": 0,
        "interviews_list": [],
        "neg_ids": [],
        "auth_error": False,
    }
    cutoff = datetime.now().astimezone() - timedelta(days=60)

    # ── Шаг 1: точный счёт интервью через state=INTERVIEW фильтр ──────────────
    for page in range(max_pages):
        try:
            resp = requests.get(
                f"https://hh.ru/applicant/negotiations?filter=all&state=INTERVIEW&page={page}",
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

            # Извлекаем ID переговоров: HH рендерит элементы кнопками, без href-ссылок,
            # ID хранятся как chatId во встроенном JSON страницы
            page_neg_ids = re.findall(r'"chatId"\s*:\s*(\d+)', body)
            for nid in page_neg_ids:
                if nid not in result["neg_ids"]:
                    result["neg_ids"].append(nid)

            parts = re.split(r'data-qa="negotiations-item"', body)
            if len(parts) <= 1:
                break

            items_on_page = 0
            for item in parts[1:]:
                items_on_page += 1
                item = re.sub(r'^[^>]*>', '', item, count=1)

                result["interview"] += 1

                # chatId для каждого элемента
                neg_id_match = re.search(r'"chatId"\s*:\s*(\d+)', item)
                item_neg_id = neg_id_match.group(1) if neg_id_match else ""
                if item_neg_id and item_neg_id not in result["neg_ids"]:
                    result["neg_ids"].append(item_neg_id)

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
                    try:
                        dt = datetime.fromisoformat(date_match.group(1).replace("Z", "+00:00"))
                        date_str = dt.strftime("%d.%m")
                        is_recent = dt >= cutoff
                    except Exception:
                        date_str = date_match.group(1)[:10]
                if is_recent:
                    result["recent_interview"] += 1
                result["interviews_list"].append({
                    "text": text_body[:120],
                    "date": date_str,
                    "recent": is_recent,
                    "neg_id": item_neg_id,
                })

            if items_on_page == 0:
                break

        except Exception as e:
            log_debug(f"fetch_hh_negotiations_stats interviews page={page} error: {e}")
            break

    if result["auth_error"]:
        return result

    # ── Шаг 2: просмотры / отказы с общей страницы ────────────────────────────
    for page in range(max_pages):
        try:
            resp = requests.get(
                f"https://hh.ru/applicant/negotiations?page={page}",
                cookies=cookies,
                headers=headers,
                timeout=15,
            )
            if resp.status_code != 200:
                break
            body = resp.text
            if _is_login_page(body):
                break

            parts = re.split(r'data-qa="negotiations-item"', body)
            if len(parts) <= 1:
                break

            items_on_page = 0
            for item in parts[1:]:
                items_on_page += 1
                item = re.sub(r'^[^>]*>', '', item, count=1)
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

            if items_on_page == 0:
                break

        except Exception as e:
            log_debug(f"fetch_hh_negotiations_stats general page={page} error: {e}")
            break

    return result


def _fetch_chat_list(acc: dict, max_pages: int = 5) -> tuple:
    """Fetch paginated chat list from /chat/messages API.
    Returns (items_by_id, display_info, current_participant_id).
    items_by_id: {str(item_id): item_dict}
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, */*",
        "Referer": "https://hh.ru/applicant/negotiations",
    }
    items_by_id: dict = {}
    display_info: dict = {}
    current_participant_id: str = ""

    for page_num in range(max_pages):
        # Список чатов HH использует параметр page=; nextFrom всегда null
        url = f"https://hh.ru/chat/messages?page={page_num}"
        try:
            resp = requests.get(url, cookies=acc["cookies"], headers=headers, timeout=15)
            if resp.status_code in (401, 403) or _is_login_page(resp.text):
                break
            if resp.status_code != 200:
                break
            data = resp.json()
        except Exception as e:
            log_debug(f"_fetch_chat_list error: {e}")
            break

        chats_data = data.get("chats", {})
        chats_obj = chats_data.get("chats") or {}
        items = chats_obj.get("items", [])
        display_info.update(chats_data.get("chatsDisplayInfo", {}))

        for item in items:
            item_id = str(item.get("id", ""))
            if item_id:
                items_by_id[item_id] = item
            if not current_participant_id:
                current_participant_id = item.get("currentParticipantId", "")

        if not chats_obj.get("hasNextPage"):
            break

    return items_by_id, display_info, current_participant_id


# Фразы, которые означают, что сообщения в чате отключены: закрыто работодателем или только по приглашению
_LOCKED_CHAT_PHRASES = (
    "работодатель отключил переписку",
    "переписка будет доступна после приглашения",
)

def _check_chat_locked(item: dict) -> str:
    """Return lock reason string if chat has messaging disabled, else empty string."""
    last_msg = item.get("lastMessage") or {}
    last_text = (last_msg.get("text") or "").lower()
    for phrase in _LOCKED_CHAT_PHRASES:
        if phrase in last_text:
            return last_text[:80]
    # Также проверяем флаги элемента: canSendMessage, locked, state и т. д.
    if item.get("canSendMessage") is False or item.get("locked") is True:
        return "canSendMessage=false"
    state = str(item.get("state") or item.get("chatState") or "").lower()
    if state in ("locked", "closed", "disabled", "invitation_required"):
        return f"state={state}"
    return ""


def _build_thread_from_chat_item(item: dict, display_info: dict, cur_pid: str, neg_id: str) -> dict:
    """Build a thread result dict from a /chat/messages item."""
    result = {"neg_id": neg_id, "employer_name": "Работодатель", "vacancy_title": "",
              "messages": [], "needs_reply": False, "last_msg_id": "", "last_employer_msg": "",
              "topic_id": "", "error": "", "chat_locked": ""}

    info = display_info.get(str(neg_id), display_info.get(str(item.get("id", "")), {}))
    result["employer_name"] = (info.get("subtitle") or "Работодатель").strip(" ,")
    result["vacancy_title"] = (info.get("title") or "").strip()

    last_msg = item.get("lastMessage") or {}
    last_text = (last_msg.get("text") or "").strip()
    last_msg_id = str(last_msg.get("id", ""))
    unread = item.get("unreadCount", 0)

    # Сначала проверяем блокировку чата: если он закрыт, ответ невозможен независимо от отправителя
    lock_reason = _check_chat_locked(item)
    if lock_reason:
        result["chat_locked"] = lock_reason
        result["last_msg_id"] = last_msg_id or str(hash(last_text))
        log_debug(f"_build_thread {neg_id}: чат заблокирован — {lock_reason!r}")
        return result

    # Отправитель: сравниваем participantId с currentParticipantId
    sender_id = last_msg.get("participantId", "")
    from_employer = bool(sender_id and cur_pid and sender_id != cur_pid)

    # Проверяем workflow-переходы: пропускаем только строковые системные события (REJECTION, APPLICATION и т. д.)
    # Числовой wf.id - внутренняя ссылка на сообщение, не системное событие; это реальный текст работодателя
    wf = last_msg.get("workflowTransition") or {}
    wf_id = wf.get("id", "") if isinstance(wf, dict) else ""
    is_workflow_msg = isinstance(wf_id, str) and bool(wf_id)  # Только строковые типы считаются системными событиями

    needs_reply = (unread > 0) and from_employer and not is_workflow_msg
    result["needs_reply"] = needs_reply
    result["last_msg_id"] = last_msg_id or str(hash(last_text))

    if last_text:
        sender = "employer" if from_employer else "applicant"
        result["messages"] = [{"sender": sender, "text": last_text, "msg_id": last_msg_id}]
        if from_employer:
            result["last_employer_msg"] = last_text

    resources = (item.get("resources") or {})
    neg_topics = resources.get("NEGOTIATION_TOPIC", [])
    if neg_topics:
        result["topic_id"] = str(neg_topics[0])

    return result


def fetch_negotiation_thread(acc: dict, neg_id: str) -> dict:
    """Fetch info for a single negotiation thread (chatId = neg_id).
    Fetches the full paginated chat list and finds the matching entry.
    Returns {neg_id, employer_name, vacancy_title, messages, needs_reply,
             last_msg_id, last_employer_msg, topic_id, error}
    """
    result = {"neg_id": neg_id, "employer_name": "Работодатель", "vacancy_title": "",
              "messages": [], "needs_reply": False, "last_msg_id": "", "last_employer_msg": "",
              "topic_id": "", "error": ""}
    try:
        items_by_id, display_info, cur_pid = _fetch_chat_list(acc, max_pages=5)
        item = items_by_id.get(str(neg_id))
        if not item:
            result["error"] = "чат не найден"
            log_debug(f"fetch_negotiation_thread {neg_id}: not in {list(items_by_id.keys())[:5]}")
            return result
        return _build_thread_from_chat_item(item, display_info, cur_pid, neg_id)
    except Exception as e:
        result["error"] = str(e)
        log_debug(f"fetch_negotiation_thread {neg_id}: {e}")
    return result


def _fetch_chat_history(acc: dict, chat_id: str, max_messages: int = 20) -> list:
    """Fetch full message history for a specific chat via chatik/api/chat_data.
    Returns list of {"sender": "employer"|"applicant", "text": str} dicts,
    oldest first, skipping system/workflow messages.
    """
    _ensure_chatik_cookies(acc)
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    xsrf = acc["cookies"].get("_xsrf", "")
    try:
        r = requests.get(
            "https://chatik.hh.ru/chatik/api/chat_data",
            params={"chatId": int(chat_id)},
            cookies=acc["cookies"],
            headers={
                "User-Agent": ua,
                "Accept": "application/json",
                "Referer": "https://chatik.hh.ru/",
                "Origin": "https://chatik.hh.ru",
                "X-XSRFToken": xsrf,
            },
            timeout=15,
            verify=False,
        )
        if r.status_code != 200:
            log_debug(f"_fetch_chat_history {chat_id}: HTTP {r.status_code}")
            return []
        data = r.json()
        cur_pid = str(data.get("chat", {}).get("currentParticipantId", ""))
        items = data.get("chat", {}).get("messages", {}).get("items", [])
        conversation = []
        for msg in items:
            # Пропускаем нетекстовые сообщения
            if msg.get("type") not in ("SIMPLE",):
                continue
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            # Пропускаем системные workflow-события: отказ, оффер и т. д.; только строковый wf.id.
            # Числовой wf.id - внутренняя ссылка на сообщение, не системное событие; оставляем такие сообщения.
            wf = msg.get("workflowTransition") or {}
            wf_id = wf.get("id", "") if isinstance(wf, dict) else ""
            if isinstance(wf_id, str) and wf_id:
                continue
            sender_pid = str(msg.get("participantId", ""))
            sender = "applicant" if (cur_pid and sender_pid == cur_pid) else "employer"
            conversation.append({"sender": sender, "text": text,
                                  "msg_id": str(msg.get("id", ""))})
        # Возвращаем последние max_messages записей: самый свежий контекст
        return conversation[-max_messages:]
    except Exception as e:
        log_debug(f"_fetch_chat_history {chat_id}: {e}")
        return []


def _ensure_chatik_cookies(acc: dict) -> None:
    """Fetch hhuid/crypted_hhuid from hh.ru if missing, storing them in acc['cookies'] in-place."""
    if acc["cookies"].get("hhuid"):
        return
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    try:
        r = requests.get(
            "https://hh.ru/",
            cookies=acc["cookies"],
            headers={"User-Agent": ua},
            timeout=10,
            verify=False,
            allow_redirects=True,
        )
        for cookie in r.cookies:
            if cookie.name in ("hhuid", "crypted_hhuid"):
                acc["cookies"][cookie.name] = cookie.value
                log_debug(f"_ensure_chatik_cookies: got {cookie.name} for {acc.get('name', '?')}")
    except Exception as e:
        log_debug(f"_ensure_chatik_cookies error: {e}")


def send_negotiation_message(acc: dict, neg_id: str, text: str, topic_id: str = "") -> bool:
    """Send a message in an HH negotiation thread via chatik.hh.ru/chatik/api/send."""
    import uuid as _uuid
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # Проверяем, что есть auth cookies для chatik: hhuid/crypted_hhuid
    _ensure_chatik_cookies(acc)
    xsrf = acc["cookies"].get("_xsrf", "")

    try:
        resp = requests.post(
            "https://chatik.hh.ru/chatik/api/send",
            cookies=acc["cookies"],
            headers={
                "User-Agent": ua,
                "Accept": "application/json, */*",
                "Content-Type": "application/json",
                "Referer": "https://chatik.hh.ru/",
                "Origin": "https://chatik.hh.ru",
                "X-XSRFToken": xsrf,
            },
            json={"chatId": int(neg_id), "idempotencyKey": str(_uuid.uuid4()), "text": text},
            timeout=15,
            verify=False,
        )
        log_debug(f"send via chatik/api/send {neg_id}: HTTP {resp.status_code} | {resp.text[:300]}")
        if resp.status_code in (200, 201, 204):
            return True
        if resp.status_code == 409:
            # Чата больше нет: переговоры архивированы или закрыты
            return "chat_not_found"
        return False
    except Exception as e:
        log_debug(f"send_negotiation_message {neg_id} error: {e}")
        return False


def generate_llm_reply(conversation: list, employer_name: str = "", cover_letter: str = "",
                       resume_text: str = "", vacancy_title: str = "",
                       vacancy_data: dict = None) -> str:
    """Generate a reply to employer using configured LLM (OpenAI-compatible API)."""
    global _llm_rr_index
    if not _openai_available:
        log_debug("generate_llm_reply: openai package not installed")
        return ""

    # Собираем список профилей: используем multi-profile config, иначе откатываемся к legacy-полям
    profiles = [p for p in (CONFIG.llm_profiles or []) if p.get("enabled", True) and p.get("api_key")]
    if not profiles:
        # Запасной вариант для старого формата: используем конфигурацию с одним ключом
        if not CONFIG.llm_api_key:
            return ""
        profiles = [{"api_key": CONFIG.llm_api_key, "base_url": CONFIG.llm_base_url,
                     "model": CONFIG.llm_model}]

    # Собираем список сообщений, общий для всех попыток профилей
    system = CONFIG.llm_system_prompt
    if resume_text and resume_text.strip():
        system += (
            f"\n\n---\nРезюме соискателя (используй для персонализации ответов):\n"
            f"{resume_text.strip()}\n---"
        )
    vacancy_context = _build_vacancy_context(vacancy_title, employer_name, vacancy_data)
    if vacancy_context:
        system += f"\n\n---\nVacancy context:\n{vacancy_context}\n---"
    if cover_letter and cover_letter.strip():
        system += (
            f"\n\nКонтекст: соискатель откликнулась на вакансию работодателя «{employer_name}» "
            f"со следующим сопроводительным письмом:\n\"\"\"\n{cover_letter.strip()}\n\"\"\"\n"
            "Учитывай содержание письма при ответе — не противоречь ему и будь последовательна."
        )
    messages = [{"role": "system", "content": system}]
    for msg in conversation[-8:]:
        role = "user" if msg["sender"] == "employer" else "assistant"
        messages.append({"role": role, "content": msg["text"]})

    mode = CONFIG.llm_profile_mode

    if mode == "roundrobin":
        # Выбираем один профиль по round-robin и пробуем только его
        idx = _llm_rr_index % len(profiles)
        _llm_rr_index += 1
        profile = profiles[idx]
        pname = profile.get("name") or profile.get("model") or f"профиль {idx}"
        model = profile.get("model") or "gpt-4o-mini"
        log_debug(f"generate_llm_reply: roundrobin → {pname} ({model}), {len(messages)-1} сообщений")
        try:
            client = _openai_mod.OpenAI(api_key=profile["api_key"], base_url=profile.get("base_url") or None)
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=300,
                temperature=0.7,
            )
            result = resp.choices[0].message.content.strip()
            log_debug(f"generate_llm_reply: {pname} → {len(result)} симв.")
            return result
        except Exception as e:
            log_debug(f"generate_llm_reply roundrobin {pname} error: {e}")
            return ""
    else:
        # Режим fallback: пробуем профили по порядку и возвращаем первый успешный результат
        for i, profile in enumerate(profiles):
            pname = profile.get("name") or profile.get("model") or f"профиль {i}"
            model = profile.get("model") or "gpt-4o-mini"
            log_debug(f"generate_llm_reply: fallback {i+1}/{len(profiles)} → {pname} ({model}), {len(messages)-1} сообщений")
            try:
                client = _openai_mod.OpenAI(api_key=profile["api_key"], base_url=profile.get("base_url") or None)
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=300,
                    temperature=0.7,
                )
                result = resp.choices[0].message.content.strip()
                log_debug(f"generate_llm_reply: {pname} → {len(result)} симв.")
                return result
            except Exception as e:
                log_debug(f"generate_llm_reply fallback {pname} error: {e}")
                continue
        log_debug("generate_llm_reply: все профили вернули ошибку")
        return ""


def generate_llm_questionnaire_answers(rich_questions: list, vacancy_title: str = "",
                                       company: str = "", resume_text: str = "",
                                       cover_letter: str = "") -> dict:
    """Заполняет ответы на опросник работодателя через LLM.
    rich_questions — список из _parse_questionnaire_rich().
    Возвращает {field: value} или {} при ошибке.
    """
    if not _openai_available or not rich_questions:
        return {}
    profiles = [p for p in (CONFIG.llm_profiles or []) if p.get("enabled", True) and p.get("api_key")]
    if not profiles:
        if not CONFIG.llm_api_key:
            return {}
        profiles = [{"api_key": CONFIG.llm_api_key, "base_url": CONFIG.llm_base_url, "model": CONFIG.llm_model}]

    lines = ["Заполни анкету работодателя для отклика на вакансию."]
    if vacancy_title:
        lines.append(f"Вакансия: {vacancy_title}")
    if company:
        lines.append(f"Компания: {company}")
    lines += ["", "Вопросы:"]
    if cover_letter:
        lines.append(f"Cover letter context:\n{cover_letter[:3000]}")
    if resume_text:
        lines.append(f"Resume context:\n{resume_text[:6000]}")
    for i, q in enumerate(rich_questions, 1):
        qtext = q.get("text", "")
        qtype = q.get("type", "textarea")
        if qtype == "textarea":
            lines.append(f'{i}. [текст] {qtext}')
        elif qtype == "radio":
            opts = " / ".join(f'"{o["label"]}" (value={o["value"]})' for o in q.get("options", []))
            lines.append(f'{i}. [выбор одного: {opts}] {qtext}')
        elif qtype == "checkbox":
            opts = " / ".join(f'"{o["label"]}" (value={o["value"]})' for o in q.get("options", []))
            lines.append(f'{i}. [чекбокс: {opts}] {qtext}')
    lines += [
        "",
        "Правила: пиши от первого лица (женский род), ищу удалённую работу.",
        "Для текста — 1–3 предложения, кратко и профессионально.",
        "Для radio/checkbox — верни точное value из скобок (цифру или код).",
        "",
        "Верни ТОЛЬКО JSON без пояснений:",
        "{"
    ]
    for q in rich_questions:
        lines.append(f'  "{q["field"]}": "...",')
    lines.append("}")

    system = "Ты помогаешь заполнять анкеты при трудоустройстве. Возвращай ТОЛЬКО валидный JSON, без markdown и пояснений."
    system = system + "\n\n" + (CONFIG.llm_system_prompt or "")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)}]

    for i, profile in enumerate(profiles):
        pname = profile.get("name") or f"профиль {i}"
        model = profile.get("model") or "gpt-4o-mini"
        log_debug(f"generate_llm_questionnaire_answers: {pname} ({model}), {len(rich_questions)} вопросов")
        try:
            client = _openai_mod.OpenAI(api_key=profile["api_key"], base_url=profile.get("base_url") or None)
            resp = client.chat.completions.create(
                model=model, messages=messages, max_tokens=600, temperature=0.3,
            )
            raw = resp.choices[0].message.content.strip()
            log_debug(f"generate_llm_questionnaire_answers raw: {raw[:300]}")
            # Извлекаем JSON — ищем {} блок
            json_m = re.search(r'\{[\s\S]*\}', raw)
            if json_m:
                answers = json.loads(json_m.group())
                return {k: str(v) for k, v in answers.items() if v is not None}
        except Exception as e:
            log_debug(f"generate_llm_questionnaire_answers {pname} error: {e}")
            if i < len(profiles) - 1:
                continue
    return {}


def resolve_chat_answer(conversation: list, employer_name: str = "", cover_letter: str = "",
                        resume_text: str = "", vacancy_title: str = "",
                        vacancy_data: dict = None) -> dict:
    """Unified chat answer strategy: template -> LLM -> fallback."""
    employer_messages = [m for m in (conversation or []) if m.get("sender") == "employer"]
    last_question = (employer_messages[-1].get("text") if employer_messages else "") or ""
    matched = find_answer_template(last_question)
    if matched:
        return {
            "source": "template",
            "answer": matched["answer"],
            "question": last_question,
            "metadata": {"matched_keywords": matched.get("matched_keywords", [])},
        }

    if CONFIG.llm_enabled and _openai_available and _llm_has_profile():
        answer = generate_llm_reply(
            conversation, employer_name=employer_name, cover_letter=cover_letter,
            resume_text=resume_text, vacancy_title=vacancy_title, vacancy_data=vacancy_data,
        )
        if answer:
            return {
                "source": "llm",
                "answer": answer,
                "question": last_question,
                "metadata": {"history_messages": len(conversation or [])},
            }

    return {
        "source": "fallback",
        "answer": _fallback_answer(),
        "question": last_question,
        "metadata": {"reason": "no_template_or_llm_unavailable"},
    }


def resolve_questionnaire_answers(rich_questions: list, vacancy_title: str = "",
                                  company: str = "", resume_text: str = "",
                                  cover_letter: str = "") -> dict:
    """Unified questionnaire strategy per field: template -> LLM -> fallback."""
    decisions = {}
    unanswered = []
    for q in rich_questions or []:
        field = q.get("field")
        if not field:
            continue
        matched = find_answer_template(q.get("text", ""))
        if matched:
            value = _coerce_questionnaire_answer(q, matched["answer"])
            decisions[field] = {
                "source": "template",
                "question": q.get("text", ""),
                "answer": value,
                "raw_answer": matched["answer"],
                "metadata": {"matched_keywords": matched.get("matched_keywords", [])},
            }
        else:
            unanswered.append(q)

    llm_answers = {}
    if unanswered and CONFIG.llm_fill_questionnaire and CONFIG.llm_enabled and _openai_available and _llm_has_profile():
        llm_answers = generate_llm_questionnaire_answers(
            unanswered, vacancy_title=vacancy_title, company=company,
            resume_text=resume_text, cover_letter=cover_letter,
        )

    for q in unanswered:
        field = q.get("field")
        if field in llm_answers and str(llm_answers[field]).strip():
            value = _coerce_questionnaire_answer(q, llm_answers[field])
            decisions[field] = {
                "source": "llm",
                "question": q.get("text", ""),
                "answer": value,
                "raw_answer": llm_answers[field],
                "metadata": {"vacancy_title": vacancy_title, "company": company},
            }
        else:
            fallback = _fallback_answer()
            value = _coerce_questionnaire_answer(q, fallback)
            decisions[field] = {
                "source": "fallback",
                "question": q.get("text", ""),
                "answer": value,
                "raw_answer": fallback,
                "metadata": {"reason": "no_template_or_llm_unavailable"},
            }
    return decisions


def parse_hh_lux_ssr(html: str) -> dict:
    """Извлечь SSR JSON из <template id="HH-Lux-InitialState">"""
    m = re.search(r'<template[^>]*id="HH-Lux-InitialState"[^>]*>([\s\S]*?)</template>', html)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}


def fetch_resume_stats(acc: dict) -> dict:
    """
    Статистика резюме за 7 дней + точный таймер поднятия.
    Возвращает dict с ключами: views, views_new, shows, invitations, invitations_new,
    next_touch_seconds, free_touches, global_invitations, new_invitations_total
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://hh.ru/",
    }
    result = {
        "views": 0, "views_new": 0, "shows": 0,
        "invitations": 0, "invitations_new": 0,
        "next_touch_seconds": 0, "free_touches": 0,
        "global_invitations": 0, "new_invitations_total": 0,
    }
    try:
        r = requests.get(
            "https://hh.ru/applicant/resumes",
            headers=headers, cookies=acc["cookies"], verify=False, timeout=15
        )
        ssr = parse_hh_lux_ssr(r.text)

        # Счётчики userStats
        user_stats = ssr.get("userStats", {})
        result["views_new"] = user_stats.get("new-resumes-views", 0)
        result["new_invitations_total"] = user_stats.get("new-applicant-invitations", 0)
        result["global_invitations"] = ssr.get("globalInvitations", 0)

        # Статистика по резюме
        # Структура: applicantResumesStatistics["resumes"][resume_id]["statistics"]
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
        "Referer": "https://hh.ru/applicant/resumes",
    }
    result = []
    try:
        r = requests.get(
            f"https://hh.ru/applicant/resumeview/history?resumeHash={resume_hash}",
            headers=headers, cookies=acc["cookies"], verify=False, timeout=15
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

        # Запасной вариант: парсим HTML, если SSR пустой
        if not result:
            entries = re.findall(
                r'href="/employer/(\d+)[^"]*"[^>]*>.*?<span[^>]*>([^<]+)</span>.*?'
                r'(?:<time[^>]*datetime="([^"]*)")?',
                html, re.DOTALL
            )
            seen = set()
            for employer_id, name, date in entries[:limit]:
                if employer_id not in seen:
                    seen.add(employer_id)
                    result.append({
                        "employer_id": employer_id,
                        "name": name.strip(),
                        "date": date[:10] if date else "",
                        "vacancy": "",
                    })
    except Exception as e:
        log_debug(f"fetch_resume_view_history error: {e}")
    return result


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

    # Имя: необязательный контекст
    first = _hh_ssr_str(resume.get("firstName"))
    last = _hh_ssr_str(resume.get("lastName"))
    full_name = " ".join(p for p in [first, last] if p)

    # Желаемая должность: HH хранит как [{"string": "..."}]
    title = _hh_ssr_str(resume.get("title"))
    # Также проверяем professionalRole на именованные роли
    roles = resume.get("professionalRole") or []
    role_names = [r.get("text") for r in roles if isinstance(r, dict) and r.get("text")]
    position_line = title or ", ".join(role_names[:3])
    if position_line:
        parts.append(f"Желаемая должность: {position_line}")

    # Ключевые навыки: advancedKeySkills содержит поле name, keySkills содержит {string: ...}
    adv_skills = resume.get("advancedKeySkills") or []
    if adv_skills and isinstance(adv_skills, list):
        skill_names = [s["name"] for s in adv_skills if isinstance(s, dict) and s.get("name")]
    else:
        raw_skills = resume.get("keySkills") or []
        skill_names = [_hh_ssr_str(s) for s in raw_skills if _hh_ssr_str(s)]
    if skill_names:
        parts.append(f"Ключевые навыки: {', '.join(skill_names[:30])}")

    # Опыт
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

    # Образование
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
    # Сначала пробуем SSR JSON: это более чистые структурированные данные
    ssr = parse_hh_lux_ssr(html)
    if ssr:
        result = _parse_resume_ssr(ssr)
        if result:
            return result

    # Запасной вариант: HTML-парсинг через BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    parts = []

    # Желаемая должность
    title_el = soup.find(attrs={"data-qa": "resume-block-title-position"})
    if title_el:
        parts.append(f"Желаемая должность: {title_el.get_text(strip=True)}")

    # Ключевые навыки
    skill_els = soup.find_all(attrs={"data-qa": "bloko-tag__text"})
    if not skill_els:
        skill_els = soup.find_all(attrs={"data-qa": "skills-element"})
    skills = [el.get_text(strip=True) for el in skill_els if el.get_text(strip=True)]
    if skills:
        parts.append(f"Ключевые навыки: {', '.join(skills[:30])}")

    # Опыт
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

    # О себе / дополнительная информация
    for qa in ("resume-block-additional-resume", "resume-block-skills-content"):
        about_el = soup.find(attrs={"data-qa": qa})
        if about_el:
            about_text = about_el.get_text(" ", strip=True)[:500]
            if about_text:
                parts.append(f"О себе: {about_text}")
            break

    # Образование
    edu_el = soup.find(attrs={"data-qa": "resume-block-education"})
    if edu_el:
        edu_text = edu_el.get_text(" ", strip=True)[:300]
        if edu_text:
            parts.append(f"Образование: {edu_text}")

    result = "\n\n".join(parts)
    # Последний резерв: удаляем HTML и берём первые 1500 символов текста body
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
    cached = _resume_cache.get(resume_hash)
    if cached:
        text, ts = cached
        if now - ts < _RESUME_CACHE_TTL:
            return text

    try:
        r = requests.get(
            f"https://hh.ru/resume/{resume_hash}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://hh.ru/applicant/resumes",
            },
            cookies=acc["cookies"],
            verify=False,
            timeout=15,
        )
        if r.status_code != 200:
            log_debug(f"fetch_resume_text: HTTP {r.status_code} для {resume_hash[:8]}")
            return ""
        text = _parse_resume_html(r.text)
        if text:
            _resume_cache[resume_hash] = (text, now)
            log_debug(f"fetch_resume_text: ✅ {len(text)} симв. для {resume_hash[:8]}")
        else:
            log_debug(f"fetch_resume_text: ⚠️ пустой результат для {resume_hash[:8]}")
        return text
    except Exception as e:
        log_debug(f"fetch_resume_text error: {e}")
        return ""


def auto_decline_discards(acc: dict) -> int:
    """
    Авто-отклонение дискардов в переговорах.
    Возвращает количество отклонённых.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://hh.ru/applicant/negotiations",
        "X-Xsrftoken": acc["cookies"]["_xsrf"],
    }
    declined = 0
    try:
        # Собираем topic_id дискардов (первые 5 страниц)
        topic_ids = []
        for page in range(5):
            r = requests.get(
                f"https://hh.ru/applicant/negotiations?state=DISCARD&page={page}",
                headers=headers, cookies=acc["cookies"], verify=False, timeout=15
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
        post_headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
        for tid in topic_ids[:50]:  # не более 50 за раз
            try:
                r2 = requests.post(
                    "https://hh.ru/applicant/negotiations/decline",
                    headers=post_headers,
                    cookies=acc["cookies"],
                    data=f"topicId={tid}&_xsrf={acc['cookies']['_xsrf']}",
                    verify=False, timeout=10
                )
                if r2.status_code in (200, 302):
                    declined += 1
            except Exception:
                pass
    except Exception as e:
        log_debug(f"auto_decline_discards error: {e}")
    return declined


def fetch_hh_possible_offers(acc: dict) -> list:
    """Получить список компаний, готовых пригласить (JSON API)"""
    cookies = acc["cookies"]
    xsrf = cookies.get("_xsrf", "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-XsrfToken": xsrf,
        "Accept": "application/json",
        "Referer": "https://hh.ru/applicant/negotiations",
    }
    try:
        resp = requests.get(
            "https://hh.ru/shards/applicant/negotiations/possible_job_offers",
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


__all__ = [name for name in globals() if not name.startswith("__")]
