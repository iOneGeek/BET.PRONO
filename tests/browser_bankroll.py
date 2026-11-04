"""Run with BROWSER_CHANNEL=msedge; uses only a disposable local account."""
import os
from pathlib import Path
import threading
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_ai
from test_bankroll import ledger


def run():
    test_ai.AIBetaTests.setUpClass()
    fixture = test_ai.AIBetaTests()
    fixture.setUp()
    rows = [fixture.client.post('/api/bets', json=b).get_json() for b in ledger()]
    server = make_server('127.0.0.1', 0, fixture.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get('BROWSER_CHANNEL') or None)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
            def local_only(route):
                if route.request.url.startswith(origin):
                    route.continue_()
                elif route.request.url.startswith('https://fonts.googleapis.com/'):
                    route.fulfill(status=200, content_type='text/css', body='')
                else:
                    route.abort()
            context.route('**/*', local_only)
            assert context.request.post(origin + '/api/login', data={'username': 'beta_user', 'password': 'testing123'}).status == 200
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(origin + '/app')
            page.wait_for_function('window.__ready === true')
            page.locator('#sideNav [data-route="dashboard"]').click()
            expect(page.locator('[data-metric="bankroll"] b')).to_contain_text('350,71')
            expect(page.locator('[data-metric="profit"] b')).to_contain_text('6,00')
            expect(page.locator('#bankrollBreakdown')).to_contain_text('35,29')
            for period in ['week', 'month', 'quarter', 'all']:
                page.locator(f'#per [data-p="{period}"]').click()
                expect(page.locator('#chartBankrollValue')).to_contain_text('350,71')
                points = page.evaluate('bankrollPoints([...BETS].sort((a,b)=>a.d.localeCompare(b.d)||a.id-b.id),cut())')
                assert abs(points[-1]['value'] - 350.71) < .001
                assert points[0]['value'] == (100 if period == 'all' else 370)
                expect(page.locator('#svg')).to_have_attribute('aria-label', page.evaluate("'Évolution du solde disponible de '+eur("+str(points[0]['value'])+")+ ' à '+eur(350.71)"))
            for period in ['week', 'month', 'quarter', 'all']:
                page.evaluate('(period)=>{ANALYTICS_PERIOD=period;renderAnalytics()}', period)
                assert '350,71' in page.locator('#analyticsBankrollChart').get_attribute('aria-label')
            # Settlement replaces the hold: losing must never deduct a stake twice.
            bet = rows[6]
            for result, value in [('lost', '350,71'), ('void', '371,00'), ('won', '391,90'), ('pending', '350,71')]:
                assert context.request.patch(origin + f'/api/bets/{bet["id"]}', data={'r': result}).status == 200
                page.evaluate('loadBets()')
                expect(page.locator('[data-metric="bankroll"] b')).to_contain_text(value)
            page.locator('#per [data-p="month"]').click()
            page.locator('summary').filter(has_text='Détail du solde').click()
            screenshots = os.environ.get('BANKROLL_SCREENSHOT_DIR')
            for width in [1440, 390, 320]:
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                if screenshots and width != 320:
                    page.screenshot(path=str(Path(screenshots) / f'bankroll-{width}.png'), full_page=True)
            # Flat balances at a grid boundary previously produced NaN SVG coordinates.
            page.evaluate('BETS=[];INIT=100;refresh()')
            assert 'NaN' not in page.locator('#svg').inner_html()
            assert 'Infinity' not in page.locator('#svg').inner_html()
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        test_ai.AIBetaTests.tearDownClass()
    print('Bankroll browser regression passed')


if __name__ == '__main__':
    run()
