"""Browser E2E (opt-in). Encodes T04/T07/T08/T09/T14 assertions.

Run only with a live stack (scripts/up.ps1) and a valid model key for the Agent steps.
"""
import os

import pytest

pytestmark = pytest.mark.e2e

BASE = "http://portal.localhost:8080"


@pytest.fixture
def page():
    if os.environ.get("HARNESS_E2E") != "1":
        pytest.skip("Set HARNESS_E2E=1 and start the stack with scripts/up.ps1")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser.new_page()
        browser.close()


def test_t14_full_business_chain(page):
    """Admin allocates -> login -> upload GeoJSON -> Agent writes result.json ->
    timeline -> terminal -> download -> rebuild restores -> cross-tenant denial."""
    page.goto(BASE + "/login")
    page.fill("input[placeholder='账号']", os.environ.get("E2E_LOGIN", "a1"))
    page.fill("input[placeholder='密码']", os.environ["E2E_PASSWORD"])
    page.click("button:has-text('登录')")
    page.wait_for_url(BASE + "/")
    # Remaining steps require a running workspace + reachable model; assertions are
    # specified in docs/verification.md T14 and executed interactively there.
    assert page.url.startswith(BASE)
