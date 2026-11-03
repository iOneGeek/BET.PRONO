"""Optional browser regression: pip install playwright; playwright install chromium.

Run: python tests/browser_ai.py
Set BROWSER_CHANNEL=msedge to use installed Edge, and AI_SCREENSHOT_DIR to save previews.
Uses the same disposable app/SQLite fixture as the API tests, never a live account.
"""
import io
import os
from pathlib import Path
import threading

from PIL import Image
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_ai import AIBetaTests


def run():
    AIBetaTests.setUpClass()
    fixture = AIBetaTests()
    fixture.setUp()
    server = make_server('127.0.0.1', 0, fixture.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get('BROWSER_CHANNEL') or None)
            context = browser.new_context(viewport={'width': 1440, 'height': 1100}, service_workers='block')
            # Local test has no dependency on web fonts or external services.
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
            login = context.request.post(origin + '/api/login', data={'username': 'beta_user', 'password': 'testing123'})
            assert login.status == 200
            page = context.new_page()
            errors = []
            requests = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append((request.method, request.url)))
            page.goto(origin + '/app')
            page.wait_for_function('window.__ready === true')
            page.locator('#sideNav [data-route="ai"]').click()
            expect(page.locator('#viewAI')).to_be_visible()
            expect(page.locator('#viewBankroll')).not_to_be_visible()
            page.locator('#aiSubmit').click()
            assert not any('/api/ai/analyze' in url for _, url in requests)
            page.locator('#aiSport').select_option('football')
            page.locator('#aiHome').fill('Paris Saint-Germain')
            page.locator('#aiAway').fill('Olympique de Marseille')
            page.locator('#aiSubmit').click()
            expect(page.locator('#aiReportContent')).to_be_visible()
            expect(page.locator('#aiReportTitle')).to_have_text('Démonstration — aucune prédiction')
            expect(page.locator('#aiMatch')).to_contain_text('Paris Saint-Germain — Olympique de Marseille')
            expect(page.locator('#aiChecks > div')).to_have_count(4)
            screenshots = os.environ.get('AI_SCREENSHOT_DIR')
            if screenshots:
                Path(screenshots).mkdir(parents=True, exist_ok=True)
                page.evaluate('window.scrollTo(0, 0)')
                page.screenshot(path=str(Path(screenshots) / 'bet-prono-ai-desktop.png'), full_page=True, animations='disabled')
            # Editing removes the stale report; names are rendered as text, never markup.
            page.locator('#aiHome').fill('<img src=x onerror=alert(1)>')
            expect(page.locator('#aiReportContent')).not_to_be_visible()
            page.locator('#aiSubmit').click()
            expect(page.locator('#aiMatch')).to_contain_text('<img src=x onerror=alert(1)>')
            expect(page.locator('#aiMatch img')).to_have_count(0)
            page.locator('#aiHome').fill(' PARIS ')
            page.locator('#aiAway').fill('paris')
            page.locator('#aiSubmit').click()
            expect(page.locator('#aiError')).to_contain_text('différents')
            expect(page.locator('#aiSubmit')).to_be_enabled()
            page.locator('#aiHome').fill('Paris Saint-Germain')
            page.locator('#aiAway').fill('Olympique de Marseille')

            def image_file(size=(32, 32), format='PNG'):
                output = io.BytesIO()
                Image.new('RGB', size, '#ff7518').save(output, format=format)
                return {'name': 'capture.' + format.lower(), 'mimeType': 'image/png' if format == 'PNG' else 'image/jpeg', 'buffer': output.getvalue()}

            for format in ('PNG', 'JPEG'):
                before = len(requests)
                page.locator('#aiScreenshot').set_input_files(image_file(format=format))
                expect(page.locator('#aiPreviewArea')).to_be_visible()
                assert len(requests) == before, 'A screenshot must never create a network request'
                page.locator('#aiRemoveCapture').click()
                expect(page.locator('#aiPreviewArea')).not_to_be_visible()
                assert page.locator('#aiPreview').get_attribute('src') is None
            invalid_files = [
                ({'name': 'bad.svg', 'mimeType': 'image/svg+xml', 'buffer': b'<svg/>'}, 'PNG ou JPEG'),
                ({'name': 'fake.png', 'mimeType': 'image/png', 'buffer': b'<script>alert(1)</script>'}, 'ne correspond pas'),
                ({'name': 'broken.png', 'mimeType': 'image/png', 'buffer': b'\x89PNG\r\n\x1a\ninvalid'}, 'illisible'),
                ({'name': 'large.png', 'mimeType': 'image/png', 'buffer': b'x' * (5 * 1024 * 1024 + 1)}, '5 Mo'),
                (image_file((4001, 4000)), '16 mégapixels'),
            ]
            for file, message in invalid_files:
                page.locator('#aiScreenshot').set_input_files(file)
                expect(page.locator('#aiCaptureStatus')).to_contain_text(message)
                expect(page.locator('#aiPreviewArea')).not_to_be_visible()

            # Recoverable API failures, unexpected responses and session expiry.
            api_url = '**/api/ai/analyze'
            page.route(api_url, lambda route: route.abort())
            page.locator('#aiSubmit').click()
            expect(page.locator('#aiError')).to_contain_text('Connexion impossible')
            expect(page.locator('#aiSubmit')).to_be_enabled()
            page.unroute(api_url)
            page.clock.install()
            pending = []
            page.route(api_url, lambda route: pending.append(route))
            page.locator('#aiSubmit').click()
            expect(page.locator('#aiSubmit')).to_be_disabled()
            page.locator('#aiForm').evaluate("form => form.dispatchEvent(new Event('submit', {cancelable:true}))")
            page.wait_for_function("document.getElementById('aiForm').getAttribute('aria-busy') === 'true'")
            assert len(pending) == 1, 'Duplicate submit must not send another request'
            page.clock.fast_forward(16000)
            expect(page.locator('#aiError')).to_contain_text('trop de temps')
            expect(page.locator('#aiSubmit')).to_be_enabled()
            pending[0].abort()
            page.unroute(api_url)
            for status, body, message in [
                (503, '{"error":"Service indisponible"}', 'Service indisponible'),
                (200, '{"mode":"live"}', 'Réponse inattendue'),
                (403, '{"error":"Compte suspendu"}', 'Compte suspendu'),
            ]:
                page.route(api_url, lambda route, request, status=status, body=body: route.fulfill(status=status, content_type='application/json', body=body))
                page.locator('#aiSubmit').click()
                expect(page.locator('#aiError')).to_contain_text(message)
                expect(page.locator('#aiSubmit')).to_be_enabled()
                page.unroute(api_url)

            page.locator('#aiSubmit').click()
            expect(page.locator('#aiReportContent')).to_be_visible()
            page.locator('#aiRemoveCapture').evaluate('(button) => button.click()')
            for width in [320, 390, 768, 1024, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                nav = '#mainNav' if width <= 880 else '#sideNav'
                page.locator(nav + ' [data-route="dashboard"]').click()
                expect(page.locator('#viewBankroll')).to_be_visible()
                page.locator(nav + ' [data-route="ai"]').click()
                expect(page.locator('#viewAI')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}px'
                if width == 390 and screenshots:
                    page.evaluate('window.scrollTo(0, 0)')
                    page.screenshot(path=str(Path(screenshots) / 'bet-prono-ai-mobile.png'), full_page=True, animations='disabled')
                page.locator(nav + ' [data-route="settings"]').click()
                expect(page.locator('#viewProfile')).to_be_visible()
                page.locator(nav + ' [data-route="analysis"]').click()
                expect(page.locator('#analysisSection')).to_be_visible()
                page.locator(nav + ' [data-route="ai"]').click()
            context.clear_cookies()
            page.locator('#aiSubmit').click()
            page.wait_for_url(origin + '/login')
            page.wait_for_load_state('networkidle')
            assert not errors, errors
            browser.close()
            print('Browser checks passed: desktop/mobile, navigation, validation, safe text, local images, API errors, session expiry.')
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
        AIBetaTests.tearDownClass()


if __name__ == '__main__':
    run()
