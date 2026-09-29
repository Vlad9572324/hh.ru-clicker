import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app import captcha
from app.captcha_worker import CaptchaCoordinator


def test_scan_closes_expired_gui_sessions_without_fetching():
    acc = {'user_id': 'expiry'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    captcha.claim_manual(acc, cid)
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc)], temp_states={})
    session = Mock()
    async def run():
        coord = CaptchaCoordinator(manager, SimpleNamespace(forget=Mock()))
        coord.gui_pending = {cid: {'session': session, 'created': time.monotonic() - 601}}
        coord.photo = AsyncMock()
        await coord.scan()
        assert not coord.gui_pending
        coord.photo.assert_not_called()
    asyncio.run(run())
    session.close.assert_called_once()
    assert captcha.current(acc)['manual_only']
