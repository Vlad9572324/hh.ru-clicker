"""Best-effort vision recognition using configured OpenAI-compatible profiles."""
import base64
import re
from urllib.parse import urlsplit

from app.config import CONFIG


def recognize_captcha(image_bytes: bytes) -> str | None:
    from app.llm import _make_openai_client

    profiles = [p for p in (CONFIG.llm_profiles or [])
                if p.get('enabled', True) and str(p.get('api_key') or '').strip()]
    if not profiles and CONFIG.llm_api_key.strip():
        profiles = [dict(api_key=CONFIG.llm_api_key, base_url=CONFIG.llm_base_url,
                         model=CONFIG.llm_model)]
    if not image_bytes:
        return None
    for profile in profiles:
        client = None
        try:
            # llm.py uses the OpenAI SDK; native Anthropic messages are incompatible.
            if urlsplit(profile.get('base_url') or '').hostname == 'api.anthropic.com':
                continue
            client = _make_openai_client(profile)
            response = client.with_options(timeout=15.0, max_retries=0).chat.completions.create(
                model=profile.get('model') or 'gpt-4o-mini', max_tokens=20,
                messages=[{'role': 'user', 'content': [
                    {'type': 'text', 'text': CONFIG.captcha_llm_prompt},
                    {'type': 'image_url', 'image_url': {
                        'url': 'data:image/png;base64,' + base64.b64encode(image_bytes).decode('ascii')}},
                ]}])
            answer = response.choices[0].message.content
            if not isinstance(answer, str):
                continue
            answer = answer.strip().strip('\"\'').strip()
            limit = min(8, CONFIG.captcha_llm_max_length)
            if answer.lower() != 'unclear' and 3 <= len(answer) <= limit and re.fullmatch(r'[a-zA-Z0-9]+', answer):
                return answer
        except Exception:
            # Provider errors can contain credentials and response bodies. Never log them.
            pass
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
    return None
