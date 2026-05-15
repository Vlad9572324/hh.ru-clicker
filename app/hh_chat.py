"""
HH.ru chat functions: fetch chat list, build threads, send messages, mark read.
"""

import requests

from app.logging_utils import log_debug, _is_login_page


def _ensure_chatik_cookies(acc: dict) -> None:
    """Fetch hhuid/crypted_hhuid from hh.ru if missing, storing them in acc['cookies'] in-place.

    Сериализовано через acc.get('_cookies_lock') если AccountState прокинул его в acc —
    иначе несколько workers одного аккаунта (apply+stats+LLM) могут одновременно
    перепрошивать куки и затирать друг друга → 401 (swarm-1 #8).
    """
    if acc["cookies"].get("hhuid"):
        return
    lock = acc.get("_cookies_lock")
    if lock is not None:
        # double-checked locking — пока ждали лок, другой воркер мог уже выставить
        if not lock.acquire(timeout=10):
            return
        try:
            if acc["cookies"].get("hhuid"):
                return
            _do_fetch_chatik_cookies(acc)
        finally:
            lock.release()
    else:
        _do_fetch_chatik_cookies(acc)


def _do_fetch_chatik_cookies(acc: dict) -> None:
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    try:
        r = requests.get(
            "https://hh.ru/",
            cookies=acc["cookies"],
            headers={"User-Agent": ua},
            timeout=10,
            allow_redirects=True,
        )
        for cookie in r.cookies:
            if cookie.name in ("hhuid", "crypted_hhuid"):
                acc["cookies"][cookie.name] = cookie.value
                log_debug(f"_ensure_chatik_cookies: got {cookie.name} for {acc.get('name', '?')}")
    except Exception as e:
        log_debug(f"_ensure_chatik_cookies error: {e}")


def _fetch_chat_list(acc: dict, max_pages: int = 5) -> tuple:
    """Fetch paginated chat list from chatik.hh.ru/chatik/api/chats.
    Returns (items_by_id, display_info, current_participant_id).
    items_by_id: {str(item_id): item_dict}
    """
    _ensure_chatik_cookies(acc)
    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, */*",
        "Origin": "https://chatik.hh.ru",
        "Referer": "https://chatik.hh.ru/",
        "X-XSRFToken": xsrf,
    }
    items_by_id: dict = {}
    display_info: dict = {}
    current_participant_id: str = ""

    for page_num in range(max_pages):
        url = f"https://chatik.hh.ru/chatik/api/chats?page={page_num}"
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

        chats_obj = data.get("chats", {})
        items = chats_obj.get("items", [])
        display_info.update(data.get("chatsDisplayInfo", {}))

        for item in items:
            item_id = str(item.get("id", ""))
            if item_id:
                items_by_id[item_id] = item
            if not current_participant_id:
                current_participant_id = item.get("currentParticipantId", "")

        # Check pagination: if fewer items than perPage, we've reached the end
        per_page = chats_obj.get("perPage", 20)
        if len(items) < per_page:
            break

    return items_by_id, display_info, current_participant_id


# Phrases that indicate chat messaging is disabled (employer locked or invite-only)
_LOCKED_CHAT_PHRASES = (
    "работодатель отключил переписку",
    "переписка будет доступна после приглашения",
)

def _check_chat_locked(item: dict) -> str:
    """Return lock reason string if chat has messaging disabled, else empty string."""
    # Primary: API booleans and state
    if item.get("canSendMessage") is False:
        return "canSendMessage=false"
    state = str(item.get("state") or item.get("chatState") or "").lower()
    if state in ("archived", "closed", "rejected", "locked", "disabled", "invitation_required"):
        return f"state={state}"
    if item.get("locked") is True:
        return "locked=true"
    # Fallback: phrase scan in last message text
    last_msg = item.get("lastMessage") or {}
    last_text = (last_msg.get("text") or "").lower()
    for phrase in _LOCKED_CHAT_PHRASES:
        if phrase in last_text:
            return last_text[:80]
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

    # Check for chat lock FIRST — if locked, no reply possible regardless of sender
    lock_reason = _check_chat_locked(item)
    if lock_reason:
        result["chat_locked"] = lock_reason
        result["last_msg_id"] = last_msg_id or str(hash(last_text))
        log_debug(f"_build_thread {neg_id}: чат заблокирован — {lock_reason!r}")
        return result

    # Sender: compare participantId with currentParticipantId
    sender_id = str(last_msg.get("participantId") or "").strip()
    cur_pid_norm = str(cur_pid or "").strip()
    if not sender_id:
        from_employer = True
    else:
        from_employer = bool(cur_pid_norm and sender_id != cur_pid_norm)

    # Check for workflow transitions: skip only string-type workflow events (REJECTION, APPLICATION, etc.)
    # Numeric wf.id = internal message reference, not a system event — real employer text
    wf = last_msg.get("workflowTransition") or {}
    wf_id = wf.get("id", "") if isinstance(wf, dict) else ""
    is_workflow_msg = isinstance(wf_id, str) and bool(wf_id)  # only string types = system events

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
            
        )
        if r.status_code != 200:
            log_debug(f"_fetch_chat_history {chat_id}: HTTP {r.status_code}")
            return []
        data = r.json()
        cur_pid = str(data.get("chat", {}).get("currentParticipantId", ""))
        items = data.get("chat", {}).get("messages", {}).get("items", [])
        conversation = []
        for msg in items:
            # Skip non-text message types
            if msg.get("type") not in ("SIMPLE",):
                continue
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            # Skip system workflow events (rejection, offer, etc.) — string wf.id only.
            # Numeric wf.id = internal message reference, not a system event — keep those.
            wf = msg.get("workflowTransition") or {}
            wf_id = wf.get("id", "") if isinstance(wf, dict) else ""
            if isinstance(wf_id, str) and wf_id:
                continue
            sender_pid = str(msg.get("participantId") or "").strip()
            cur_pid_norm = str(cur_pid or "").strip()
            if not sender_pid:
                sender = "employer"
            elif cur_pid_norm and sender_pid == cur_pid_norm:
                sender = "applicant"
            else:
                sender = "employer"
            pd = msg.get("participantDisplay") or {}
            conversation.append({
                "sender": sender, "text": text,
                "msg_id": str(msg.get("id", "")),
                "actions": msg.get("actions") or {},
                "is_bot": pd.get("isBot", False),
            })
        # Return last max_messages entries (most recent context)
        return conversation[-max_messages:]
    except Exception as e:
        log_debug(f"_fetch_chat_history {chat_id}: {e}")
        return []


def send_negotiation_message(acc: dict, neg_id: str, text: str, topic_id: str = "") -> bool:
    """Send a message in an HH negotiation thread via chatik.hh.ru/chatik/api/send."""
    import uuid as _uuid
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # Ensure we have chatik auth cookies (hhuid/crypted_hhuid)
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
            json={"chatId": int(str(neg_id).strip()), "idempotencyKey": str(_uuid.uuid4()), "text": text},
            timeout=15,
            
        )
        log_debug(f"send via chatik/api/send {neg_id}: HTTP {resp.status_code} | {resp.text[:300]}")
        if resp.status_code in (200, 201, 204):
            return True
        if resp.status_code == 409:
            try:
                body_json = resp.json()
            except Exception:
                body_json = {}
            err_type = str(body_json.get("error") or body_json.get("type") or "").lower()
            err_msg = str(body_json.get("message") or body_json.get("description") or "").lower()
            full_text = (resp.text or "").lower()
            if "duplicate" in err_msg or "rate" in err_msg or "duplicate" in full_text or "rate" in full_text:
                return False
            if err_type in ("chat_not_found", "archived", "closed") or "chat_not_found" in full_text or "archived" in full_text:
                return "chat_not_found"
            return False
        return False
    except Exception as e:
        log_debug(f"send_negotiation_message {neg_id} error: {e}")
        return False


def _mark_chat_read(acc: dict, chat_id: str, message_id: str):
    """Mark a chatik chat as read up to the given message ID."""
    try:
        cid = int(str(chat_id).strip())
        mid = int(str(message_id).strip())
    except (ValueError, TypeError):
        return
    _ensure_chatik_cookies(acc)
    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    try:
        requests.post(
            "https://chatik.hh.ru/chatik/api/mark_read",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                     "Accept": "application/json", "Content-Type": "application/json",
                     "Origin": "https://chatik.hh.ru", "Referer": "https://chatik.hh.ru/",
                     "X-XSRFToken": xsrf},
            cookies=acc["cookies"],
            json={"chatId": cid, "messageId": mid},
            timeout=5
        )
    except Exception as e:
        log_debug(f"_mark_chat_read {cid}: {e}")
