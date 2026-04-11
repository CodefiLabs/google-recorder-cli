import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page, Response

SESSION_DIR = Path.home() / ".recorder-cli"
SESSION_FILE = SESSION_DIR / "session.json"
RECORDER_URL = "https://recorder.google.com"


async def login() -> None:
    """Open visible browser for Google login, save session."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(RECORDER_URL)
        # Wait for user to complete login — detect by URL returning to recorder
        await page.wait_for_url(f"{RECORDER_URL}/**", timeout=300_000)
        await page.wait_for_load_state("networkidle")
        await context.storage_state(path=str(SESSION_FILE))
        await browser.close()


def has_session() -> bool:
    """Check if a saved session exists."""
    return SESSION_FILE.exists()


async def create_context(playwright) -> BrowserContext:
    """Create a browser context with saved session."""
    if not has_session():
        raise RuntimeError("No session found. Run: recorder login")
    browser = await playwright.chromium.launch(headless=True, channel="chrome")
    context = await browser.new_context(storage_state=str(SESSION_FILE))
    return context


async def intercept_response(
    page: Page,
    url_pattern: str,
    trigger_url: str,
    timeout: float = 30_000,
) -> dict:
    """Navigate to trigger_url and capture the first JSON response matching url_pattern."""
    captured: asyncio.Future[dict] = asyncio.get_event_loop().create_future()

    async def on_response(response: Response) -> None:
        if url_pattern in response.url and not captured.done():
            try:
                data = await response.json()
                captured.set_result(data)
            except Exception:
                pass

    page.on("response", on_response)
    await page.goto(trigger_url)

    try:
        return await asyncio.wait_for(captured, timeout=timeout / 1000)
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"No response matching '{url_pattern}' within {timeout/1000}s. "
            "Session may be expired. Run: recorder login"
        )
    finally:
        page.remove_listener("response", on_response)
