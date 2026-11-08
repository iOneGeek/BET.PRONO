"""Optional browser regression: pip install playwright; playwright install chromium.

Run: python tests/browser_ai.py
Set BROWSER_CHANNEL=msedge to use installed Edge, and AI_SCREENSHOT_DIR to save previews.
Uses the same disposable app/SQLite fixture as the API tests, never a live account.
"""
import os
from pathlib import Path
import threading
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch

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
            def local_assets_only(route):
                if route.request.url.startswith(origin):
                    route.continue_()
                elif route.request.url.startswith('https://fonts.googleapis.com/'):
                    route.fulfill(status=200, content_type='text/css', body='')
                else:
                    route.abort()
            context.route('**/*', local_assets_only)
            login = context.request.post(origin + '/api/login', data={'username': 'beta_user', 'password': 'testing123'})
            assert login.status == 200
            page = context.new_page()
            errors = []
            requests = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append((request.method, request.url)))
            page.goto(origin + '/app')
            page.wait_for_function('window.__ready === true')
            expect(page.locator('#jsError')).not_to_be_visible()
            page.locator('#sideNav [data-route="ai"]').click()
            expect(page.locator('#viewAI')).to_be_visible()
            expect(page.locator('#viewBankroll')).not_to_be_visible()
            for selector in ("#aiForm", "#aiScreenshot", "#aiReport"):
                expect(page.locator(selector)).to_have_count(0)
            screenshots = os.environ.get("AI_SCREENSHOT_DIR")
            if screenshots:
                Path(screenshots).mkdir(parents=True, exist_ok=True)
            page.clock.install()
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
            # Exercise the actual Flask adapter with synthetic provider responses.
            from test_sports_data import GAME, FakeResponse
            from test_match_analysis import response as model_response
            today = (datetime.now(fixture.module.FR_TZ).date() + timedelta(days=1)).isoformat()
            game = deepcopy(GAME)
            game['startTime'] = today + 'T20:00:00+01:00'
            other = {**game, 'id': 1002, 'statusGroup': 2, 'statusText': 'Scheduled'}
            pregame = deepcopy(other)
            pregame['id'] = 1003
            pregame['homeCompetitor']['recentMatches'] = [900, 901, 902]
            past = [{**deepcopy(GAME), 'id': 900 + index, 'startTime': f'2026-10-{index + 1:02}T20:00:00+02:00'} for index in range(3)]
            pregame['members'] = [{'id': 77, 'name': 'Test Striker', 'competitorId': 20}]
            pregame['awayCompetitor']['lineups'] = {'status': 'NotConfirmed', 'members': [{'id': 77, 'status': 1, 'position': {'id': 4}}]}
            pregame['topPerformers'] = {'categories': [{'awayPlayer': {'id': 77, 'stats': [{'type': 1, 'name': 'Goals', 'value': '5'}]}}]}
            def provider_response(url, **kwargs):
                if 'games/allscores' in url:
                    if kwargs['params'].get('sports') == 4:
                        return FakeResponse({'games': [hockey]})
                    if 'games' in kwargs['params']:
                        return FakeResponse({'games': past})
                    return FakeResponse({'games': [game, other, pregame]})
                if url.endswith('/game/'):
                    if kwargs['params']['gameId'] == 1004:
                        return FakeResponse({'game': hockey})
                    return FakeResponse({'game': pregame if kwargs['params']['gameId'] == 1003 else other})
                if kwargs['params']['games'] in (1002, 1003):
                    return FakeResponse({'lastUpdateId': 0, 'requestedUpdateId': 0, 'ttl': 60})
                if kwargs['params']['games'] == 1004:
                    return FakeResponse({'games': [hockey]})
                return FakeResponse({'games': [game], 'statistics': [
                    {'id': 3, 'name': 'Shots', 'competitorId': 10, 'value': '0'},
                    {'id': 3, 'name': 'Shots', 'competitorId': 20, 'value': '8'},
                    {'id': 8, 'name': 'Corners', 'competitorId': 20, 'value': '2'},
                    {'id': 9, 'name': '<img src=x>', 'competitorId': 10, 'value': '<script>test</script>'},
                ]})
            with patch('sports_data.requests.get', side_effect=provider_response) as get, patch('match_analysis.requests.post', return_value=model_response()) as generate, patch.dict(fixture.app.config, {'GEMINI_API_KEY': 'test-only-key'}):
                page.locator('#liveDate').fill(today)
                page.locator('#liveQuery').fill('Paris')
                page.locator('#liveSearch').click()
                expect(page.locator('#liveMatches button')).to_have_count(3)
                page.locator('#liveMatches button').first.click()
                expect(page.locator('#liveReport')).to_be_visible()
                expect(page.locator('#liveScore')).to_have_text('0 — 2')
                expect(page.locator('#liveStatsBody')).to_contain_text('Indisponible')
                expect(page.locator('#liveStatsBody img')).to_have_count(0)
                expect(page.locator('#liveStatsBody script')).to_have_count(0)
                expect(page.locator('#liveDetailFreshness')).to_contain_text('365Scores')
                expect(page.locator('#liveAnalysisContent')).to_be_visible()
                expect(page.locator('#liveAnalysisSummary')).to_have_text('Les tirs observés sont déséquilibrés.')
                expect(page.locator('#liveAnalysisPoints')).to_contain_text('Données citées')
                assert 'Gemini' not in page.locator('#viewAI').inner_text()
                assert generate.call_count == 1
                for width in (320, 390, 768, 1440):
                    page.set_viewport_size({'width': width, 'height': 900})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Live view overflow at {width}'
                    if screenshots and width in (390, 1440):
                        suffix = 'mobile' if width == 390 else 'desktop'
                        page.locator('.ai-live').screenshot(path=str(Path(screenshots) / f'365scores-test-{suffix}.png'), animations='disabled')
                page.locator('#liveMatches button').nth(1).click()
                expect(page.locator('#liveNoStats')).to_be_visible()
                expect(page.locator('#liveError')).not_to_be_visible()
                expect(page.locator('#liveScore')).to_have_text('Score indisponible')
                expect(page.locator('#liveStatsWrap')).not_to_be_visible()
                expect(page.locator('#liveAnalysisStatus')).to_contain_text('insuffisantes')
                expect(page.locator('#liveAnalysisContent')).not_to_be_visible()
                assert generate.call_count == 1
                with patch.dict(fixture.app.config, {'GEMINI_API_KEY': ''}):
                    page.locator('#liveMatches button').first.click()
                    expect(page.locator('#liveAnalysisStatus')).to_contain_text('clé du service d’analyse est absente')
                    expect(page.locator('#liveStatsWrap')).to_be_visible()
                fixture.module.match_analyzer._cache.clear()
                with patch('match_analysis.requests.post', return_value=FakeResponse(status=429)) as quota:
                    page.locator('#liveMatches button').first.click()
                    expect(page.locator('#liveAnalysisStatus')).to_contain_text('quota du service d’analyse est atteint')
                    expect(page.locator('#liveStatsWrap')).to_be_visible()
                    page.locator('#liveMatches button').first.click()
                    expect(page.locator('#liveAnalysisStatus')).to_contain_text('quota du service d’analyse est atteint')
                    quota.assert_called_once()
                # A late analysis for one match must never replace another match's report.
                analysis_url = '**/api/ai/matches/1001/analysis'
                delayed = []
                page.route(analysis_url, lambda route: delayed.append(route))
                with page.expect_request('**/api/ai/matches/1001/analysis'):
                    page.locator('#liveMatches button').first.click()
                expect(page.locator('#liveAnalysisStatus')).to_contain_text('Préparation')
                page.locator('#liveMatches button').nth(1).click()
                expect(page.locator('#liveAnalysisStatus')).to_contain_text('insuffisantes')
                assert len(delayed) == 1
                delayed[0].abort()
                page.unroute(analysis_url)
                expect(page.locator('#liveAnalysisContent')).not_to_be_visible()
                expect(page.locator('#liveMatchMeta')).to_contain_text('1002')
                # Invalid model/API response and timeout do not hide the sports data.
                page.route(analysis_url, lambda route: route.fulfill(status=200, content_type='application/json', body='{"status":"ready","summary":"bad"}'))
                page.locator('#liveMatches button').first.click()
                expect(page.locator('#liveAnalysisStatus')).to_contain_text('indisponible')
                expect(page.locator('#liveStatsWrap')).to_be_visible()
                page.unroute(analysis_url)
                delayed = []
                page.route(analysis_url, lambda route: delayed.append(route))
                with page.expect_request('**/api/ai/matches/1001/analysis'):
                    page.locator('#liveMatches button').first.click()
                expect(page.locator('#liveAnalysisStatus')).to_contain_text('Préparation')
                page.clock.fast_forward(36000)
                expect(page.locator('#liveAnalysisStatus')).to_contain_text('indisponible')
                delayed[0].abort()
                page.unroute(analysis_url)
                expect(page.locator('#liveStatsWrap')).to_be_visible()
                # A scheduled match can generate an analysis from verified past results.
                fixture.module.match_analyzer._blocked_until = 0
                history_answer = {'summary': 'Les résultats passés donnent un premier contexte.', 'observations': [
                    {'text': 'Test Paris a perdu face à Test Lyon sur le score de 0 à 2.', 'fact_ids': ['home_recent_0']}],
                    'prediction': {'home_goals': 0, 'away_goals': 2, 'scorer_id': 77,
                                   'fact_ids': ['home_recent_0', 'away_recent_0', 'player_77']}}
                with patch('match_analysis.requests.post', return_value=model_response(history_answer)) as history_generate:
                    page.locator('#liveMatches button').nth(2).click()
                    expect(page.locator('#liveRecent')).to_be_visible()
                    expect(page.locator('#liveRecentTeams')).to_contain_text('01/10/2026')
                    expect(page.locator('#liveRecentTeams')).to_contain_text('0 — 2')
                    expect(page.locator('#liveStatsWrap')).not_to_be_visible()
                    expect(page.locator('#liveAnalysisSummary')).to_have_text(history_answer['summary'])
                    expect(page.locator('#liveAnalysisContent')).to_be_visible()
                    expect(page.locator('#livePrediction')).to_be_visible()
                    expect(page.locator('#livePredictionWinner')).to_have_text('Test Lyon')
                    expect(page.locator('#livePredictionScore')).to_have_text('Test Paris 0 — 2 Test Lyon')
                    expect(page.locator('#livePredictionScorer')).to_contain_text('Test Striker')
                    expect(page.locator('#livePredictionScorerNote')).to_contain_text('composition à confirmer')
                    history_generate.assert_called_once()
                    for width in (390, 1440):
                        page.set_viewport_size({'width': width, 'height': 900})
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        if screenshots:
                            page.locator('.ai-live').screenshot(path=str(Path(screenshots) / f'prediction-{width}.png'), animations='disabled')
                page.locator('#liveQuery').fill('No such test team')
                expect(page.locator('#livePrediction')).not_to_be_visible()
                expect(page.locator('#liveReport')).not_to_be_visible()
                expect(page.locator('#liveMatches button')).to_have_count(0)
                page.locator('#liveSearch').click()
                expect(page.locator('#liveStatus')).to_contain_text('Aucune rencontre')
                self_count = get.call_count
                assert self_count == 7, f'Expected cached search and details; got {self_count} provider calls'
                # Start an independent hockey session window after the rapid football regression scenarios.
                fixture.module.sports_client._users.clear()
                hockey = {**game, 'id': 1004, 'sportId': 4, 'statusGroup': 3, 'statusText': '1st Intermission',
                          'stages': [{'id': 40, 'shortName': 'P1', 'homeCompetitorScore': 0, 'awayCompetitorScore': 2}],
                          'events': [{'stageId': 40, 'gameTimeDisplay': '04:15', 'competitorId': 10,
                                      'eventType': {'name': 'Penalty'}}]}
                page.locator('#liveSport').select_option('hockey')
                page.locator('#liveQuery').fill('')
                page.locator('#liveSearch').click()
                page.locator('#liveMatches button').first.click()
                expect(page.locator('#trackerPhase')).to_have_text('Fin du premier tiers')
                expect(page.locator('#trackerEvents')).to_contain_text('04:15')
                expect(page.locator('#trackerEvents')).to_contain_text('Pénalité')
                expect(page.locator('#trackerPeriods')).to_contain_text('0 : 2')
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                with page.expect_request('**/1004/tracker'):
                    page.clock.fast_forward(62000)
                expect(page.locator('#trackerRefresh')).to_be_enabled()
                page.locator('#liveQuery').fill('Madrid')
                expect(page.locator('#matchTracker')).not_to_be_visible()
            page.route('**/api/ai/matches?*', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"Source indisponible"}'))
            page.locator('#liveSearch').click()
            expect(page.locator('#liveError')).to_have_text('Source indisponible')
            expect(page.locator('#liveSearch')).to_be_enabled()
            page.unroute('**/api/ai/matches?*')
            context.clear_cookies()
            page.locator('#liveSearch').click()
            page.wait_for_url(origin + '/login')
            page.wait_for_load_state('networkidle')
            assert not errors, errors
            browser.close()
            print('Browser checks passed: demo removed, sports search/detail, pregame score/winner/scorer, missing statistics, safe text, responsive layouts, provider errors and session expiry.')
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
        AIBetaTests.tearDownClass()


if __name__ == '__main__':
    run()
