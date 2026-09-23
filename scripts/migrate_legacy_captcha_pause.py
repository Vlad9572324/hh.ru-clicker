"""Offline one-account migration after verified captcha_required log evidence.

Stop service first. Does NOT fetch a challenge, solve it or resume automation.
"""
import json
from pathlib import Path
from app.captcha import hold
from app.storage import _atomic_write_json


def main():
    path = Path('data/browser_sessions.json')
    sessions = json.loads(path.read_text())
    if len(sessions) != 1:
        raise RuntimeError('Expected one verified account')
    acc = sessions[0]
    if not acc.get('paused') or acc.get('paused_reason') != 'auto_errors':
        raise RuntimeError('Pause changed; do not modify')
    if any(acc.get(k) for k in ('pending_apply', 'pending_applies', 'hard_stopped', 'limit_exceeded')):
        raise RuntimeError('Other protective state present')
    hold(acc, {})  # Old code discarded the challenge URL; never invent one.
    acc['paused_reason'] = 'challenge'
    _atomic_write_json(path, sessions)
    print('Legacy CAPTCHA pause preserved; manual HH check required.')


if __name__ == '__main__':
    main()
