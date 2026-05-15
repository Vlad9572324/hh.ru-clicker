"""
HH.ru apply functions: send response, fill questionnaire, check vacancy, check limit, touch resume.
"""

import re
import json
import time
import requests
import aiohttp

from glom import glom

from app.logging_utils import log_debug, _is_login_page
from app.config import CONFIG
from app.hh_api import get_headers
from app.oauth import _oauth_touch_resume
from app.questionnaire import _parse_questionnaire_fields, _parse_questionnaire_rich
from app.llm import _randomize_text, generate_llm_questionnaire_answers
from app.hh_resume import fetch_resume_text

try:
    import openai as _openai_mod
    _openai_available = True
except ImportError:
    _openai_available = False


_HH_DEFAULT_TIMEOUT = 15


def _parse_retry_after(value: str) -> int | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        return max(0, int(dt.timestamp() - time.time()))
    except Exception:
        return None


def _with_retry(func, retries=3, backoff_base=2.0):
    def wrapper(*args, **kwargs):
        for attempt in range(retries + 1):
            try:
                resp = func(*args, **kwargs)
                if hasattr(resp, "status_code") and resp.status_code in (502, 503, 504):
                    if attempt == retries:
                        return resp
                    sleep = backoff_base * (2 ** attempt)
                    log_debug(f"_with_retry {getattr(func, '__name__', 'unknown')}: HTTP {resp.status_code}, sleep {sleep}s ({attempt+1}/{retries+1})")
                    time.sleep(sleep)
                    continue
                return resp
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt == retries:
                    raise
                sleep = backoff_base * (2 ** attempt)
                log_debug(f"_with_retry {getattr(func, '__name__', 'unknown')}: {type(e).__name__}, sleep {sleep}s ({attempt+1}/{retries+1})")
                time.sleep(sleep)
        return func(*args, **kwargs)
    wrapper.__name__ = getattr(func, "__name__", "unknown")
    return wrapper


def classify_apply_response(status_code: int, txt: str) -> tuple:
    """Pure: классифицирует ответ HH popup на отклик в (result, info).
    Вынесено из send_response_async чтобы было тестируемо без mock'ов HTTP.

    Порядок проверок важен:
    1. 401/403 → auth_error
    2. 200 + login-page HTML → auth_error
    3. известные error-маркеры в теле (limit/test/already) — даже на 200, т.к. HH
       отдаёт их с status=200 (см. audit C5)
    4. 200 + success-маркер → sent
    5. всё остальное → error
    """
    if status_code in (401, 403):
        return "auth_error", {}

    if status_code == 200 and _is_login_page(txt):
        return "auth_error", {}

    info = {}
    if "shortVacancy" in txt:
        try:
            p = json.loads(txt)
            info = {
                "title": glom(p, "responseStatus.shortVacancy.name", default=""),
                "company": glom(p, "responseStatus.shortVacancy.company.name", default=""),
                "salary_from": glom(p, "responseStatus.shortVacancy.compensation.from", default=None),
                "salary_to": glom(p, "responseStatus.shortVacancy.compensation.to", default=None),
            }
            ci = glom(p, "responseStatus.shortVacancy.contactInfo", default={})
            if ci and (ci.get("email") or ci.get("fio")):
                contact = {"fio": ci.get("fio", ""), "email": ci.get("email", ""), "phone": ""}
                phones = (ci.get("phones") or {}).get("phones", [])
                if phones:
                    ph = phones[0]
                    contact["phone"] = f"+{ph.get('country','')}{ph.get('city','')}{ph.get('number','')}"
                info["contact"] = contact
        except Exception:
            pass

    if "negotiations-limit-exceeded" in txt:
        return "limit", info
    if "test-required" in txt:
        return "test", info
    if "alreadyApplied" in txt:
        return "already", info

    if status_code == 200:
        if ('"success":true' in txt or '"status":"ok"' in txt
                or '"responded":true' in txt or "shortVacancy" in txt):
            return "sent", info
        return "error", {"raw": txt[:200], **info}

    if status_code in (502, 503, 504):
        return "error", {"raw": txt[:200], "transient": True, **info}

    return "error", {"raw": txt[:200], **info}


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
                timeout=aiohttp.ClientTimeout(total=_HH_DEFAULT_TIMEOUT)
            ) as r:
                txt = await r.text()
                status_code = r.status

        log_debug(f"   Ответ HTTP: {status_code} | Размер: {len(txt)}")
        if status_code >= 400:
            log_debug(f"   Тело ответа: {txt[:300]}")
        return classify_apply_response(status_code, txt)
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
            async with session.get(url_form, timeout=aiohttp.ClientTimeout(total=_HH_DEFAULT_TIMEOUT)) as r:
                html = await r.text()
                status_code = r.status

            # Auth check: 401/403/login-page → не считать "test" (валидный отклик),
            # а отдать auth_error чтобы воркер обновил куки/спаузил аккаунт.
            if status_code in (401, 403) or _is_login_page(html):
                return "auth_error", {}
            if status_code != 200:
                return "error", {"http_status": status_code}

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
                        if field not in rich_fields:
                            # Free-text or unknown field — only accept scalars
                            if isinstance(llm_val, (str, int, float, bool)):
                                validated_ans[field] = str(llm_val)
                            continue
                        q = rich_fields[field]
                        if not (q["type"] in ("radio", "checkbox", "select") and q["options"]):
                            if isinstance(llm_val, (str, int, float, bool)):
                                validated_ans[field] = str(llm_val)
                            continue
                        valid_values = [o["value"] for o in q["options"]]
                        # Checkbox may legitimately receive a list of selected values
                        if q["type"] == "checkbox" and isinstance(llm_val, list):
                            picked = []
                            for item in llm_val:
                                if not isinstance(item, (str, int, float, bool)):
                                    continue
                                s = str(item).strip()
                                if s in valid_values:
                                    picked.append(s)
                                else:
                                    fuzzy = [v for v in valid_values if v.lower().strip() == s.lower()]
                                    if fuzzy:
                                        picked.append(fuzzy[0])
                            if picked:
                                validated_ans[field] = picked
                            else:
                                log_debug(f"LLM checkbox {field}: nothing matched in {llm_val} vs {valid_values}")
                            continue
                        # Scalar option (radio/select or single checkbox value as string)
                        if not isinstance(llm_val, (str, int, float, bool)):
                            log_debug(f"LLM {q['type']} {field}: unexpected type {type(llm_val).__name__}, skipping")
                            continue
                        s = str(llm_val).strip()
                        if s in valid_values:
                            validated_ans[field] = s
                        else:
                            fuzzy = [v for v in valid_values if v.lower().strip() == s.lower()]
                            if fuzzy:
                                validated_ans[field] = fuzzy[0]
                            else:
                                log_debug(f"LLM answer '{s}' not in options {valid_values}, skipping field {field}")
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
                # checkbox с несколькими выбранными значениями → несколько полей одного name
                if isinstance(value, list):
                    for v in value:
                        data.add_field(name, str(v))
                else:
                    data.add_field(name, str(value))

            # Шаг 3: POST
            async with session.post(
                url_form,
                headers={"X-Xsrftoken": acc.get("cookies", {}).get("_xsrf", ""), "Referer": url_form},
                data=data,
                timeout=aiohttp.ClientTimeout(total=_HH_DEFAULT_TIMEOUT),
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
        r = _with_retry(
            lambda: requests.get(
                f"https://hh.ru/applicant/vacancy_response/popup?vacancyId={vid}",
                headers={"User-Agent": ua, "Accept": "application/json, */*",
                         "Referer": f"https://hh.ru/vacancy/{vid}"},
                cookies=acc.get("cookies", {}),
                timeout=_HH_DEFAULT_TIMEOUT,
            ),
            retries=3, backoff_base=2.0,
        )()
        if r.status_code in (401, 403) or _is_login_page(r.text):
            return {"ok": False, "reason": "auth_error", "skip_reason": "auth"}
        if r.status_code == 429:
            retry_after = _parse_retry_after(r.headers.get("Retry-After", ""))
            result = {"ok": False, "reason": "rate_limit", "skip_reason": "retry"}
            if retry_after is not None:
                result["retry_after_seconds"] = retry_after
            return result
        if r.status_code >= 500:
            # HH server issue — попробовать позже.
            return {"ok": False, "reason": f"http_{r.status_code}", "skip_reason": "retry"}
        if r.status_code != 200:
            # 4xx (другие, кроме 401/403/429) — permanent skip.
            return {"ok": False, "reason": f"http_{r.status_code}", "skip_reason": "skip"}
        try:
            data = r.json()
        except (json.JSONDecodeError, ValueError):
            return {"ok": False, "reason": "bad_json", "skip_reason": "parse_error"}
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
        # Fail-closed: на любой неожиданной ошибке лучше пропустить вакансию,
        # чем зря потратить лимит откликов.
        return {"ok": False, "reason": str(e), "skip_reason": "exception"}


def check_limit(acc: dict) -> bool:
    """True если лимит активен. Uses GET popup (no side effects)."""
    # GET popup — safe, no side effects, no wasted apply slots
    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    if not xsrf:
        return True
    try:
        r_search = _with_retry(
            lambda: requests.get(
                "https://hh.ru/search/vacancy?text=&area=1&page=0",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                         "Accept": "text/html"},
                cookies=acc["cookies"], timeout=_HH_DEFAULT_TIMEOUT,
            ),
            retries=3, backoff_base=2.0,
        )()
        vids = re.findall(r'/vacancy/(\d+)', r_search.text)
        if not vids:
            return True
        vid = vids[0]
        # Use GET popup — safe, no side effects
        r = _with_retry(
            lambda: requests.get(
                f"https://hh.ru/applicant/vacancy_response/popup?vacancyId={vid}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                         "Accept": "application/json", "X-Xsrftoken": xsrf},
                cookies=acc["cookies"], timeout=_HH_DEFAULT_TIMEOUT,
            ),
            retries=3, backoff_base=2.0,
        )()
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
        response = _with_retry(
            lambda: requests.post(
                "https://hh.ru/applicant/resumes/touch",
                headers=headers,
                cookies=acc["cookies"],
                files=touch_files,
                timeout=_HH_DEFAULT_TIMEOUT
            ),
            retries=3, backoff_base=2.0,
        )()

        if response.status_code == 200:
            return True, "Резюме поднято (web)!"
        elif response.status_code == 429:
            return False, "Слишком часто (429)"
        else:
            return False, msg or f"HTTP {response.status_code}"

    except Exception as e:
        return False, msg or f"Ошибка: {str(e)[:30]}"
