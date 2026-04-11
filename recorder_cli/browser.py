import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page, Response

SESSION_DIR = Path.home() / ".recorder-cli"
PROFILE_DIR = SESSION_DIR / "chrome-profile"
RECORDER_URL = "https://recorder.google.com"

# Args that hide Playwright automation flags from Google's bot detection
_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]


async def login() -> None:
    """Open visible browser for Google login, save profile."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        # launch_persistent_context builds a real browser profile on disk.
        # Google treats this as a real user vs. an isolated new_context() which it blocks.
        context = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            channel="chrome",
            args=_STEALTH_ARGS,
        )
        page = await context.new_page()
        await page.goto(RECORDER_URL)
        await asyncio.get_event_loop().run_in_executor(
            None,
            input,
            "\nSign in to your Google account in the browser window.\nPress Enter here when you're done...\n",
        )
        await context.close()


def has_session() -> bool:
    """Check if a saved browser profile exists."""
    return PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir())


async def create_context(playwright) -> BrowserContext:
    """Create a headless browser context using the saved profile."""
    if not has_session():
        raise RuntimeError("No session found. Run: recorder login")
    return await playwright.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        headless=True,
        channel="chrome",
        args=_STEALTH_ARGS,
    )


async def intercept_response(
    page: Page,
    url_pattern: str,
    trigger_url: str,
    timeout: float = 30_000,
) -> dict:
    """Navigate to trigger_url and capture the first JSON response matching url_pattern."""
    loop = asyncio.get_event_loop()
    captured: asyncio.Future[dict] = loop.create_future()

    def on_response(response: Response) -> None:
        if url_pattern in response.url and not captured.done():
            async def _read():
                try:
                    data = await response.json()
                    if not captured.done():
                        captured.set_result(data)
                except Exception:
                    pass
            asyncio.ensure_future(_read())

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
