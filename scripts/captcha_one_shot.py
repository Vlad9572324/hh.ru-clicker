"""Operator-authorized ONE application, keeping the running account paused.

Run only with explicit permission. Durable marker prevents accidental reruns.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from app import captcha, apply_quarantine
from app.oauth import _oauth_headers, _token_key
from app.hh_http import HH
from app.storage import _atomic_write_json, add_applied, is_applied


def main():
    marker = Path('data/captcha_one_shot.json')
    if marker.exists():
        raise RuntimeError('One-shot already reserved; no automatic retry')
    accounts = json.loads(Path('data/browser_sessions.json').read_text())
    assert len(accounts) == 1
    acc = accounts[0]
    assert acc.get('paused') and acc.get('paused_reason') == 'challenge'
    assert not any(acc.get(k) for k in ('pending_apply', 'pending_applies', 'hard_stopped', 'limit_exceeded'))
    headers = _oauth_headers(acc)
    assert headers
    # Previously selected by this account's search, rejected with captcha_required.
    vid = '137630781'
    assert not apply_quarantine.blocked(acc, vid) and not is_applied(acc['name'], vid)
    response = HH.get('https://api.hh.ru/vacancies/' + vid, headers=headers,
                      cookie_jar_key=_token_key(acc), timeout=15)
    assert response.status_code == 200, 'Vacancy unavailable; no application sent'
    vacancy = response.json()
    assert not vacancy.get('archived') and not vacancy.get('has_test')
    assert not vacancy.get('response_letter_required')
    assert not vacancy.get('relations'), 'Existing relation; do not apply'
    record = {'vacancy_id': vid, 'resume_id': acc['resume_hash'], 'flow': 'apply',
              'recorded_at': datetime.now(timezone.utc).isoformat(), 'reason_code': 'transport_unknown'}
    _atomic_write_json(marker, {**record, 'result': 'reserved'})
    apply_quarantine.retain(acc, record)
    # No redirects, transport fallback or retries for this authorized write.
    response = HH.post('https://api.hh.ru/negotiations', headers=headers,
                       data={'vacancy_id': vid, 'resume_id': acc['resume_hash']},
                       cookie_jar_key=_token_key(acc), timeout=15,
                       _force_requests=True, allow_redirects=False, _skip_diag=True)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    challenge = captcha.capture(acc, response.status_code, payload)
    result = 'challenge' if challenge else 'unknown'
    if response.status_code in (201, 204):
        result = 'sent'
        add_applied(acc['name'], vid, {'title': vacancy.get('name', ''),
                    'company': vacancy.get('employer', {}).get('name', '')})
    _atomic_write_json(marker, {**record, 'result': result, 'http_status': response.status_code})
    print(json.dumps({'result': result, 'http_status': response.status_code,
                      'has_direct_link': bool(captcha.browser_url(captcha.current(acc))),
                      'account_remains_paused': True}))


if __name__ == '__main__':
    main()
