import asyncio
import logging
import random

from playwright.async_api import async_playwright


async def get_etsid(userid: str, password: str) -> str | None:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()

            # stealth 적용 (필수)
            try:
                from playwright_stealth import Stealth
                stealth = Stealth()
                await stealth.apply_stealth_async(page)
                logging.info("stealth 모드 적용됨")
            except ImportError:
                logging.warning("playwright-stealth 미설치 — pip install playwright-stealth 실행 필요")

            await page.goto("https://everytime.kr/login", timeout=30000)

            # 페이지 완전 로드 대기
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(random.uniform(0.5, 1.0))

            await page.fill('input[name="id"]', userid)
            await asyncio.sleep(random.uniform(0.3, 0.7))

            await page.fill('input[name="password"]', password)
            await asyncio.sleep(random.uniform(0.3, 0.7))

            # 클릭 후 URL 변경 대기 (networkidle보다 안정적)
            await page.click('input[type="submit"]')

            try:
                # 로그인 성공 시 URL이 바뀜
                await page.wait_for_url(
                    lambda url: "login" not in url,
                    timeout=15000
                )
            except Exception:
                # URL 안 바뀌면 로그인 실패 (reCAPTCHA 등)
                # 디버깅용 스크린샷 저장
                await page.screenshot(path="login_failed.png")
                logging.error("로그인 후 URL 미변경 — login_failed.png 확인")
                await browser.close()
                return None

            # 리다이렉트 완전히 끝날 때까지 대기
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(1.0)

            # 명시적 도메인 지정으로 쿠키 수집
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

            await browser.close()

            if etsid:
                logging.info("etsid 획득 성공")
            else:
                logging.warning("etsid 없음 — 쿠키 목록 확인 요망")

            return etsid

    except Exception as e:
        logging.error(f"로그인 실패: {e}")
        return None