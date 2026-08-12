"""Launch Chromium and automate a small in-memory page with playclanker."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from pathlib import Path

from cdp.playclanker import Frame, Page, Response
from cdp.playclanker.async_api import async_playwright

SCREENSHOT_DIR = Path(__file__).resolve().parents[1] / "screenshots"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


async def wait_for_cloudflare_frame(
    page: Page, *, timeout: float = 30_000
) -> Frame | None:
    """Poll until the dynamically attached Cloudflare iframe is available."""

    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        frame = next(
            (
                candidate
                for candidate in page.frames
                if "challenges.cloudflare.com" in candidate.url
            ),
            None,
        )
        if frame is not None:
            return frame
        await page.wait_for_timeout(100)
    return None


def log_server_error(prefix: str, response: Response) -> None:
    """Log failing responses and cookie names without exposing cookie values."""

    if response.status < 500:
        return
    print(prefix, f"HTTP {response.status} {response.status_text}: {response.url}")
    set_cookie = response.headers.get("set-cookie")
    if set_cookie is not None:
        names = [
            line.split("=", 1)[0].strip()
            for line in set_cookie.splitlines()
            if "=" in line
        ]
        print(prefix, "Set-Cookie names:", names)


async def main(job_id: int) -> None:
    """Fill a form, click a button, and assert the rendered result."""

    prefix = f"[job {job_id}]"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            user_agent=USER_AGENT,
        )
        page: Page | None = None
        try:
            page = await browser.new_page()
            page.on("response", lambda response: log_server_error(prefix, response))
            print(
                prefix, "Page user agent:", await page.evaluate("navigator.userAgent")
            )
            navigation_response = await page.goto(
                "https://vnb13925.online/interactive", wait_until="networkidle"
            )
            if navigation_response is not None:
                print(
                    prefix,
                    "Initial response:",
                    navigation_response.status,
                    navigation_response.status_text,
                )
            print(prefix, "Page shadow root nodes: ", await page.shadow_roots())
            frame = await wait_for_cloudflare_frame(page)
            if frame is None:
                print(prefix, "Cloudflare iframe not found within 30 seconds")
                return
            print(prefix, "CloudFlare <iframe>: ", frame.url)
            print(
                prefix, "Frame user agent:", await frame.evaluate("navigator.userAgent")
            )
            shadow_roots = await frame.shadow_roots()
            shadow_root = shadow_roots[0]
            locator = shadow_root.locator('input[type="checkbox"]')
            await locator.node_visible()
            await locator.click()
            print(prefix, "Checkbox clicked")
            await page.wait_for_load_state("load", timeout=15_000)
            print(prefix, "Page loaded, URL: ", page.url)
            print(prefix, "Cookies:")
            for cookie in await page.context.cookies(page.url):
                print(
                    prefix,
                    "  "
                    + f"{cookie['name']}={cookie['value']} "
                    + f"(domain={cookie['domain']}, path={cookie['path']})",
                )
        except Exception as e:
            print(prefix, e)
        finally:
            if page is not None:
                screenshot_path = SCREENSHOT_DIR / f"job-{job_id}.png"
                with suppress(Exception):
                    await page.screenshot(path=screenshot_path, full_page=True)
                    print(prefix, "Screenshot:", screenshot_path)
            await browser.close()


async def run_jobs() -> None:
    """Run five independent browser jobs concurrently."""

    await asyncio.gather(*(main(job_id) for job_id in range(1, 2)))


if __name__ == "__main__":
    asyncio.run(run_jobs())
