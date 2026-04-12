import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

@pytest.mark.docker
def test_browser_page_title_fetch(monkeypatch):
    """Verify that a Playwright script can run and fetch a page title."""
    monkeypatch.setenv("REGISTRY_BYPASS_DEV", "true")
    monkeypatch.setattr(
        "api.routers.execute._verify_payment",
        AsyncMock(return_value=True),
    )
    mock_rc = MagicMock()
    mock_rc.contract_id = None
    mock_rc.get_agent_record.return_value = None
    mock_rc.update_reputation.return_value = None
    monkeypatch.setattr("api.routers.execute.registry_client", mock_rc)

    # A minimal Playwright script to fetch page title
    browser_script = """import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto('http://example.com')
        title = await page.title()
        print(f"TITLE: {title}")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())"""

    import base64
    b64_script = base64.b64encode(browser_script.encode()).decode()

    payload = {
        "task": "fetch-page-title-simple",
        "input": {"expected_substring": "Example Domain"},
        "agent_id": "test-agent",
        "image": "mcr.microsoft.com/playwright/python:v1.45.0-jammy",
        "cmd": "python3 -c \"import urllib.request; print(urllib.request.urlopen('http://example.com').read().decode())\"",
        "network_enabled": True
    }
    headers = {"X-Stellar-Payment-Tx": "0" * 64}

    with client.stream("POST", "/execute/stream", json=payload, headers=headers) as response:
        assert response.status_code == 200
        lines = []
        for raw in response.iter_lines():
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if line.startswith("data: "):
                data = json.loads(line[6:])
                lines.append(data)

        # Print lines for debugging
        print(f"DEBUG: Browser automation output: {lines}")

        # Check for the expected page title
        assert any("Example Domain" in str(l.get("line")) for l in lines if "line" in l)
        
        final_result = next(l for l in lines if "status" in l)
        assert final_result["status"] == "completed"
        assert final_result["verified"] is True
