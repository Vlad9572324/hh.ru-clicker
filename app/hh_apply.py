"""
HH.ru apply functions: send response, fill questionnaire, check vacancy, check limit, touch resume.
"""

import re
import json
import requests
import aiohttp

from glom import glom

from app.logging_utils import log_debug, _is_login_page
from app.config import CONFIG
from app.hh_api import get_headers
from app.oauth import _oauth_touch_resume
from app.questionnaire import _parse_questionnaire_fields, _parse_questionnaire_rich, get_questionnaire_answer
from app.llm import _randomize_text, generate_llm_questionnaire_answers
from app.hh_resume import fetch_resume_text

try:
    import openai as _openai_mod
    _openai_available = True
except ImportError:
    _openai_available = False


async def send_response_async(acc: dict, vid: str) -> tuple:
    """Асинхронная отправка отклика. Возвращает (результат, инфо)"""
    log_debug(f"📤 ОТПРАВКА ОТКЛИКА на вакансию {vid} | Аккаунт: {acc['name']}")

    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    if not xsrf:
        return "error", {"exception": "Missing _xsrf token"}
    headers = get_headers(xsrf)

    letter = _randomize_text(acc.get("letter", ""))

    data = aiohttp.FormData()
    data.add_field("resume_hash", acc["resume_hash"])
    data.add_field("vacancy_id", vid)
    data.add_field("letterRequired", "true")
    data.add_field("letter", letter)
    data.add_field("lux", "true")
    data.add_field("ignore_postponed", "true")

    try:
        async with aiohttp.ClientSession(headers=headers, cookies=acc["cookies"]) as session:
            async with session.post(
                "https://hh.ru/applicant/vacancy_response/popup",
                data=data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                txt = await r.text()
                status_code = r.status

        log_debug(f"   Ответ HTTP: {status_code} | Размер: {len(txt)}")
        if status_code >= 400:
            log_debug(f"   Тело ответа: {txt[:300]}")

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
                    # Extract HR contact info
                    ci = glom(p, "responseStatus.shortVacancy.contactInfo", default={})
                    if ci and (ci.get("email") or ci.get("fio")):
                        contact = {"fio": ci.get("fio", ""), "email": ci.get("email", ""), "phone": ""}
                        phones = (ci.get("phones") or {}).get("phones", [])
                        if phones:
                            ph = phones[0]
                            contact["phone"] = f"+{ph.get('country','')}{ph.get('city','')}{ph.get('number','')}"
                        info["contact"] = contact
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
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            return "test", info

        if "alreadyApplied" in txt:
            return "already", {}

        return "error", {"raw": txt[:200]}
    except Exception as e:
        return "error", {"exception": str(e)}


async def fill_and_submit_questionnaire(acc: dict, vid: str,
                                        vacancy_title: str = "", company: str = "") -> tuple:
    """
    Получает страницу опроса, заполняет шаблонными ответами и отправляет.
    Поддерживает textarea, radio, checkbox.
    Возвращает (result, info): result = sent | limit | test | error
    """
    headers_get = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"https://hh.ru/vacancy/{vid}",
    }

    try:
        async with aiohttp.ClientSession(
            cookies=acc["cookies"],
            headers=headers_get
        ) as session:
            url_form = f"https://hh.ru/applicant/vacancy_response?vacancyId={vid}&withoutTest=no"

            # Шаг 1: GET форма опроса
            async with session.get(url_form, timeout=aiohttp.ClientTimeout(total=15)) as r:
                html = await r.text()

            # Hidden поля
            hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
            hidden.update(dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+type="hidden"[^>]+value="([^"]*)"', html)))

            # Парсим все поля опроса
            questions, field_answers = _parse_questionnaire_fields(html)

            if not field_answers:
                log_debug(f"Questionnaire: no task fields found for {vid}")
                return "test", {}

            # LLM-заполнение опросника (если включено)
            if CONFIG.llm_fill_questionnaire and CONFIG.llm_enabled and _openai_available and questions:
                rich_qs = _parse_questionnaire_rich(html)
                resume_text = ""
                if CONFIG.llm_use_resume:
                    resume_text = fetch_resume_text(acc)
                llm_ans = generate_llm_questionnaire_answers(rich_qs, vacancy_title, company, resume_text=resume_text)
                if llm_ans:
                    # Validate LLM answers against actual options
                    rich_fields = {q["field"]: q for q in rich_qs}
                    validated_ans = {}
                    for field, llm_val in llm_ans.items():
                        if field in rich_fields:
                            q = rich_fields[field]
                            if q["type"] in ("radio", "checkbox", "select") and q["options"]:
                                valid_values = [o["value"] for o in q["options"]]
                                if llm_val in valid_values:
                                    validated_ans[field] = llm_val
                                else:
                                    # Try fuzzy match (case-insensitive strip)
                                    matched = [v for v in valid_values if v.lower().strip() == llm_val.lower().strip()]
                                    if matched:
                                        validated_ans[field] = matched[0]
                                    else:
                                        log_debug(f"LLM answer '{llm_val}' not in options {valid_values}, skipping field {field}")
                            else:
                                validated_ans[field] = llm_val
                        else:
                            validated_ans[field] = llm_val
                    overridden = [f for f in validated_ans if f in field_answers]
                    for f in overridden:
                        field_answers[f] = validated_ans[f]
                    log_debug(f"Questionnaire {vid}: LLM заполнил {len(overridden)}/{len(field_answers)} полей: {overridden}")
                else:
                    log_debug(f"Questionnaire {vid}: LLM вернул пустой ответ, используем шаблоны")

            log_debug(f"Questionnaire {vid}: {len(field_answers)} fields, {len(questions)} questions")
            for name, val in field_answers.items():
                log_debug(f"  {name} = {str(val)[:80]}")

            # Шаг 2: POST данные
            data = aiohttp.FormData()
            data.add_field("resume_hash", acc["resume_hash"])
            data.add_field("vacancy_id", vid)
            data.add_field("letter", _randomize_text(acc.get("letter", "")))
            data.add_field("lux", "true")

            for name in ("_xsrf", "uidPk", "guid", "startTime", "testRequired"):
                if name in hidden:
                    data.add_field(name, hidden[name])

            for name, value in field_answers.items():
                data.add_field(name, str(value))

            # Шаг 3: POST
            async with session.post(
                url_form,
                headers={"X-Xsrftoken": acc.get("cookies", {}).get("_xsrf", ""), "Referer": url_form},
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
                return "sent", {}

            if status == 200:
                if "negotiations-limit-exceeded" in txt:
                    return "limit", {}
                if "test-required" in txt:
                    return "test", {}
                return "sent", {}

            return "test", {}

    except Exception as e:
        log_debug(f"fill_and_submit_questionnaire error: {e}")
        return "error", {"exception": str(e)}


def _check_vacancy_before_apply(acc: dict, vid: str) -> dict:
    """Pre-check vacancy before applying: detect impossible responses and experience mismatches.
    Returns {"ok": bool, "reason": str}
    """
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    try:
        r = requests.get(
            f"https://hh.ru/applicant/vacancy_response/popup?vacancyId={vid}",
            headers={"User-Agent": ua, "Accept": "application/json, */*",
                     "Referer": f"https://hh.ru/vacancy/{vid}"},
            cookies=acc.get("cookies", {}),
            timeout=10,
        )
        if r.status_code not in (200,):
            return {"ok": True, "reason": ""}  # can't check, allow
        data = r.json()
        # Check responseImpossible
        resp_status = data.get("responseStatus") or {}
        if resp_status.get("responseImpossible"):
            reason = resp_status.get("responseImpossibleReason", "responseImpossible")
            return {"ok": False, "reason": str(reason)}
        # Check resume inconsistencies (experience type mismatch)
        body = data.get("body", {})
        inner_rs = body.get("responseStatus", resp_status)
        incon_data = inner_rs.get("resumeInconsistencies", resp_status.get("resumeInconsistencies", {}))
        if isinstance(incon_data, dict):
            for resume_entry in incon_data.get("resume", []):
                for inc in (resume_entry.get("inconsistencies", {}).get("inconsistency", [])):
                    if inc.get("type") == "EXPERIENCE":
                        return {"ok": False, "reason": f"опыт: нужен {inc.get('required','?')}, есть {inc.get('actual','?')}"}
        elif isinstance(incon_data, list):
            for inc in incon_data:
                if isinstance(inc, dict) and inc.get("type") == "EXPERIENCE":
                    return {"ok": False, "reason": f"несовпадение опыта"}

        # Extract contactInfo if available
        contact = {}
        sv = inner_rs.get("shortVacancy", {})
        ci = sv.get("contactInfo", {})
        if ci and (ci.get("email") or ci.get("fio")):
            contact = {
                "fio": ci.get("fio", ""),
                "email": ci.get("email", ""),
                "phone": "",
            }
            phones = ci.get("phones", {}).get("phones", [])
            if phones:
                p = phones[0]
                contact["phone"] = f"+{p.get('country','')}{p.get('city','')}{p.get('number','')}"

        return {"ok": True, "reason": "", "contact": contact}
    except Exception as e:
        log_debug(f"_check_vacancy_before_apply {vid}: {e}")
        return {"ok": True, "reason": ""}  # on error, allow apply


def check_limit(acc: dict) -> bool:
    """True если лимит активен. Uses GET popup (no side effects)."""
    # GET popup — safe, no side effects, no wasted apply slots
    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    if not xsrf:
        return True
    try:
        r_search = requests.get(
            "https://hh.ru/search/vacancy?text=&area=1&page=0",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                     "Accept": "text/html"},
            cookies=acc["cookies"], timeout=10,
        )
        vids = re.findall(r'/vacancy/(\d+)', r_search.text)
        if not vids:
            return True
        vid = vids[0]
        # Use GET popup — safe, no side effects
        r = requests.get(
            f"https://hh.ru/applicant/vacancy_response/popup?vacancyId={vid}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                     "Accept": "application/json", "X-Xsrftoken": xsrf},
            cookies=acc["cookies"], timeout=10,
        )
        return "negotiations-limit-exceeded" in r.text
    except Exception:
        return True


def touch_resume(acc: dict) -> tuple:
    """
    Поднять резюме в поиске.
    Tries OAuth API first (no captcha), falls back to web.
    Возвращает (success: bool, message: str)
    """
    # Try OAuth first — no captcha!
    ok, msg = _oauth_touch_resume(acc)
    if ok:
        return True, msg
    if "429" not in msg:
        log_debug(f"touch_resume OAuth failed: {msg}, trying web fallback")

    # Fallback to web (may hit captcha)
    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    if not xsrf:
        return False, msg or "Missing _xsrf token"
    headers = get_headers(xsrf)
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
            return True, "Резюме поднято (web)!"
        elif response.status_code == 429:
            return False, "Слишком часто (429)"
        else:
            return False, msg or f"HTTP {response.status_code}"

    except Exception as e:
        return False, msg or f"Ошибка: {str(e)[:30]}"
