"""
HH.ru negotiations: fetch stats, possible offers, auto-decline discards.
"""

import re
import requests
from datetime import datetime, timedelta

from app.logging_utils import log_debug, _is_login_page
from app.hh_resume import parse_hh_lux_ssr


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
        "unread_by_employer": 0,  # count of negotiations where employer hasn't read our messages
    }
    cutoff = datetime.now().astimezone() - timedelta(days=60)
    seen_interview_ids: set = set()  # для дедупа при битой пагинации HH

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

            # Extract negotiation IDs: HH renders items as buttons (no href links),
            # IDs are stored as chatId in the page's embedded JSON
            page_neg_ids = re.findall(r'"chatId"\s*:\s*(\d+)', body)
            for nid in page_neg_ids:
                if nid not in result["neg_ids"]:
                    result["neg_ids"].append(nid)

            parts = re.split(r'data-qa="negotiations-item"', body)
            if len(parts) <= 1:
                break

            items_on_page = 0
            new_items_on_page = 0
            for item in parts[1:]:
                items_on_page += 1
                item = re.sub(r'^[^>]*>', '', item, count=1)

                # chatId per item — дедуп по нему, чтобы повторная страница не накручивала interview
                neg_id_match = re.search(r'"chatId"\s*:\s*(\d+)', item)
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

            parts = re.split(r'data-qa="negotiations-item"', body)
            if len(parts) <= 1:
                break

            items_on_page = 0
            new_items_on_page = 0
            for item in parts[1:]:
                items_on_page += 1
                item = re.sub(r'^[^>]*>', '', item, count=1)
                # Dedup by chatId — HH иногда повторяет страницы
                neg_id_match = re.search(r'"chatId"\s*:\s*(\d+)', item)
                key = neg_id_match.group(1) if neg_id_match else f"page{page}_idx{items_on_page}"
                if key in seen_general_keys:
                    continue
                seen_general_keys.add(key)
                new_items_on_page += 1

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
        "Referer": "https://hh.ru/applicant/negotiations",
        "X-Xsrftoken": xsrf,
    }
    declined = 0
    try:
        # Собираем topic_id дискардов (первые 5 страниц)
        topic_ids = []
        for page in range(5):
            r = requests.get(
                f"https://hh.ru/applicant/negotiations?state=DISCARD&page={page}",
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
                    "https://hh.ru/applicant/negotiations/decline",
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
