import asyncio
import json
import logging
import random


def _load_browser_state(storage) -> dict | None:
    if storage is None:
        return None
    try:
        value = storage.load("browser_state")
        if value:
            return json.loads(value)
    except Exception as e:
        logging.warning(f"브라우저 상태 로드 실패: {e}")
    return None


async def _save_browser_state(context, storage) -> None:
    if storage is None:
        return
    try:
        state = await context.storage_state()
        storage.save("browser_state", json.dumps(state))
        logging.info("브라우저 상태 저장됨")
    except Exception as e:
        logging.warning(f"브라우저 상태 저장 실패: {e}")


async def get_etsid(userid: str, password: str, storage=None) -> str | None:
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            stored_state = _load_browser_state(storage)
            if stored_state:
                context = await browser.new_context(storage_state=stored_state)
                logging.info("저장된 브라우저 상태로 컨텍스트 복원")
            else:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/121.0.0.0 Safari/537.36"
                    )
                )

            page = await context.new_page()

            try:
                from playwright_stealth import Stealth
                await Stealth().apply_stealth_async(page)
                logging.info("stealth 모드 적용됨")
            except ImportError:
                logging.warning("playwright-stealth 미설치")

            await page.goto("https://everytime.kr/login", timeout=30000)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(random.uniform(0.5, 1.0))

            await page.fill('input[name="id"]', userid)
            await asyncio.sleep(random.uniform(0.3, 0.7))
            await page.fill('input[name="password"]', password)
            await asyncio.sleep(random.uniform(0.3, 0.7))

            await page.click('input[type="submit"]')

            try:
                await page.wait_for_url(
                    lambda url: "login" not in url,
                    timeout=15000
                )
            except Exception:
                await page.screenshot(path="login_failed.png")
                logging.error("로그인 후 URL 미변경 — login_failed.png 확인")
                await browser.close()
                return None

            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(1.0)

            all_cookies = await context.cookies([
                "https://everytime.kr",
                "https://account.everytime.kr",
                "https://api.everytime.kr"
            ])

            logging.info(f"수집된 쿠키 목록: {[c['name'] for c in all_cookies]}")

            etsid = next(
                (c["value"] for c in all_cookies if c["name"] == "etsid"),
                None
            )

            if etsid:
                await _save_browser_state(context, storage)
                logging.info("etsid 획득 성공")
            else:
                logging.warning("etsid 없음 — 쿠키 목록 확인 요망")

            await browser.close()
            return etsid

    except Exception as e:
        logging.error(f"로그인 실패: {e}")
        return None
