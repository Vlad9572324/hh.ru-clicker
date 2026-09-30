"""Vision recognition of HH captchas by model consensus.

HH's captcha is two (often nonsense) Russian words written along an arc. Single
models read ~40-50% of them correctly. A benchmark on 15 real captchas
(2026-09-30) showed that submitting only when >=4 of 8 readings (4 models x 2)
agree solves about 3 of 4 captchas with no wrong submissions. HH records a wrong
answer as isBot, so without consensus we return None and a human solves it.
"""
import base64
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from app.config import CONFIG

_PROMPT = ("Это капча HH.ru: два русских слова (часто бессмысленные или обрезанные), написанные по дуге. "
           "Прочитай их точно по буквам слева направо, не исправляй на похожие настоящие слова. "
           "Ответь только этими двумя словами строчными буквами через один пробел.")
_OPENAI_MODELS = ("gpt-4.1-mini", "gpt-4o-mini", "gpt-4o", "gpt-4.1")
_SAMPLES = 2
_MIN_VOTES = 4
_WORDS = re.compile(r"[а-яё]+(?: [а-яё]+){1,2}")


def _normalize(text):
    value = " ".join(str(text or "").strip().strip("\"'«»").lower().split())
    return value if 3 <= len(value) <= 40 and _WORDS.fullmatch(value) else None


def _vote_key(answer):
    return answer.replace("ё", "е")


def _readers(profile):
    """(model, samples, votes needed). Non-OpenAI endpoints only have their own model."""
    host = urlsplit(profile.get("base_url") or "").hostname or "api.openai.com"
    if host == "api.openai.com":
        return [m for m in _OPENAI_MODELS for _ in range(_SAMPLES)], _MIN_VOTES
    model = profile.get("model") or "gpt-4o-mini"
    return [model] * 3, 3


def _read(profile, model, image_bytes):
    from app.llm import _make_openai_client
    client = None
    try:
        client = _make_openai_client(profile)
        response = client.with_options(timeout=15.0, max_retries=1).chat.completions.create(
            model=model, max_tokens=40,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii"),
                    "detail": "high"}},
            ]}])
        return _normalize(response.choices[0].message.content)
    except Exception:
        # Provider errors can contain credentials and response bodies. Never log them.
        return None
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def recognize_captcha(image_bytes: bytes) -> str | None:
    profiles = [p for p in (CONFIG.llm_profiles or [])
                if p.get("enabled", True) and str(p.get("api_key") or "").strip()]
    if not profiles and CONFIG.llm_api_key.strip():
        profiles = [dict(api_key=CONFIG.llm_api_key, base_url=CONFIG.llm_base_url, model=CONFIG.llm_model)]
    if not image_bytes:
        return None
    for profile in profiles:
        # llm.py uses the OpenAI SDK; native Anthropic messages are incompatible.
        if urlsplit(profile.get("base_url") or "").hostname == "api.anthropic.com":
            continue
        models, need = _readers(profile)
        with ThreadPoolExecutor(4) as pool:
            answers = [a for a in pool.map(lambda m: _read(profile, m, image_bytes), models) if a]
        if not answers:
            continue  # this provider is down: try the next profile
        winner, votes = Counter(_vote_key(a) for a in answers).most_common(1)[0]
        if votes < need:
            return None
        # Keep "ё" when the models wrote it.
        return Counter(a for a in answers if _vote_key(a) == winner).most_common(1)[0][0]
    return None
