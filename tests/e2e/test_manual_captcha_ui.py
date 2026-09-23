from playwright.sync_api import expect


def test_missing_link_cannot_claim_completed_captcha(ui):
    ui.state['accounts'][0].update(paused=True, paused_reason='challenge', cookies_expired=False,
        hard_stopped=False, limit_exceeded=False, pending_apply=None, pending_applies=[])
    ui.open()
    ui.page.route('**/api/account/0/captcha', lambda route: route.fulfill(json={
        'ok': True, 'id': 'legacy', 'has_direct_link': False, 'url': ''}))
    ui.page.locator('#acc-captcha-0 button').click()
    box = ui.page.locator('#acc-captcha-result-0')
    expect(box.locator('a')).to_have_count(0)
    expect(box.locator('button')).to_have_text('Проверить API без отклика')


def test_captcha_link_and_explicit_confirmation(ui):
    acc = ui.state['accounts'][0]
    acc.update(paused=True, paused_reason='challenge', cookies_expired=False,
               hard_stopped=False, limit_exceeded=False, pending_apply=None, pending_applies=[])
    ui.open()
    ui.page.route('**/api/account/0/captcha', lambda route: route.fulfill(json={
        'ok': True, 'id': 'synthetic-challenge', 'has_direct_link': True,
        'url': 'https://hh.ru/account/captcha?state=synthetic&backurl=https%3A%2F%2Fhh.ru%2F'}))
    ui.page.evaluate("document.getElementById('acc-captcha-0').hidden = true")
    ui.push_state()
    expect(ui.page.locator('#acc-captcha-0')).to_be_visible()
    expect(ui.page.locator('#acc-pause-btn-0')).to_be_disabled()
    expect(ui.page.locator('#acc-captcha-result-0 a')).to_have_text('Пройти капчу на HH ↗')
    expect(ui.page.locator('#acc-captcha-result-0 a')).to_have_attribute('target', '_blank')
    requests = []
    def resume(route):
        requests.append(route.request.post_data_json)
        route.fulfill(json={'ok': True, 'message': 'Продолжение разрешено вами'})
    ui.page.route('**/api/account/0/captcha/continue', resume)
    ui.page.once('dialog', lambda dialog: dialog.dismiss())
    ui.page.locator('#acc-captcha-result-0 button').click()
    assert requests == []
    ui.page.once('dialog', lambda dialog: dialog.accept())
    ui.page.locator('#acc-captcha-result-0 button').click()
    expect(ui.page.locator('#acc-captcha-result-0')).to_contain_text('Продолжение разрешено')
    assert requests == [{'id': 'synthetic-challenge', 'confirmed': True}]
