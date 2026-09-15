"""Desktop checks for new bounded-loop stop reasons; all API traffic is mocked."""
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fixtures', ROOT / 'qa-ui.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def main():
    pagination = 'pagination' in sys.argv[1:]
    prefix = 'pagination' if pagination else 'round-efficiency'
    out = ROOT / f'{prefix}-screenshots'
    out.mkdir(exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for language in ('zh', 'en'):
            context = browser.new_context()
            context.add_init_script(f"localStorage.setItem('extrio.language', '{language}')")
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            run = deepcopy(fixtures.RUN)

            def api(route):
                assert route.request.method == 'GET'
                if '/auth/state' in route.request.url:
                    body = {'authEnabled': False, 'authenticated': True, 'setupRequired': False,
                            'user': {'id': 'qa', 'username': 'qa', 'role': 'administrator'}}
                elif '/ai-runs/' in route.request.url:
                    body = run
                else:
                    body = {'items': []}
                route.fulfill(status=200, content_type='application/json', body=json.dumps(body))

            page.route('**/api/v1/**', api)
            cases = [(code, 4) for code in ('PAGINATION_NEXT_LINK_MISSING', 'PAGINATION_OMITTED', 'PAGINATION_MODE_MISMATCH')] if pagination else [('MODEL_NO_PROGRESS', 4), ('MODEL_DISCOVERY_BUDGET_EXCEEDED', 12)]
            for code, calls in cases:
                run.update(status='failed', phase='failed', resultStatus='no_candidate', reviewStatus='not_ready',
                           candidateRuleDigest=None)
                run['evidence'].update(phase='failed', validated=False)
                run['evidence']['budget'].update(calls=calls, maxCalls=16, stopReason='MODEL_NO_PROGRESS' if pagination else code)
                if pagination:
                    run['evidence']['validation'] = [{'code': code, 'field': 'list.pagination', 'stage': 'list'}]
                for width, height in ((1440, 900), (1280, 800), (1132, 1028), (1024, 800)):
                    page.set_viewport_size({'width': width, 'height': height})
                    page.goto(fixtures.URL + '/ai-runs/ai_run_qa?section=process')
                    error = page.locator('.adaptive-evidence .ai-run-error')
                    expect(error).to_be_visible()
                    assert code not in error.inner_text()
                    if pagination:
                        expect(page.locator('.adaptive-evidence')).to_contain_text('list.pagination')
                        expect(page.locator('.adaptive-validation')).not_to_contain_text(code)
                    measurements = page.evaluate('''() => {
                      const e = document.querySelector('.adaptive-evidence .ai-run-error');
                      const r = e.getBoundingClientRect();
                      return {overflow: document.documentElement.scrollWidth > innerWidth,
                        errorClipped: e.scrollWidth > e.clientWidth + 2,
                        errorFits: r.left >= 0 && r.right <= innerWidth};
                    }''')
                    assert not measurements['overflow'] and not measurements['errorClipped'] and measurements['errorFits']
                    page.screenshot(path=str(out / f'{code}-{language}-{width}.png'), full_page=True)
                    results.append({'code': code, 'language': language, 'width': width, **measurements})
            assert not errors, errors
            context.close()
        browser.close()
    (ROOT / f'{prefix}-ui.json').write_text(json.dumps({'results': results, 'realApiWrites': 0}, indent=2))
    print(f'{len(results)} desktop checks passed; zero real API writes')


if __name__ == '__main__':
    main()
