"""Generic XHR interceptor for CRA sites."""
import asyncio, sys
from playwright.async_api import async_playwright

async def probe(url, wait_ms=6000):
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True,
            args=["--disable-blink-features=AutomationControlled"])
        ctx = await b.new_context(ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
        pg = await ctx.new_page()
        hits = []
        async def on_resp(r):
            ct = r.headers.get("content-type", "")
            if ("json" in ct) and r.status == 200:
                try:
                    body = await r.text()
                    if len(body) > 150 and "gtm" not in r.url:
                        hits.append((r.url, body[:500]))
                except Exception:
                    pass
        pg.on("response", on_resp)
        try:
            await pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            await pg.wait_for_timeout(wait_ms)
        except Exception as e:
            print("NAV ERROR:", str(e)[:150])
        print("PAGE TITLE:", await pg.title())
        for u, body in hits[:8]:
            print("\nURL:", u)
            print("BODY:", body.replace("\n"," ")[:400])
        if not hits:
            # dump visible text sample as fallback
            txt = await pg.inner_text("body")
            print("\nNO JSON XHR. BODY TEXT SAMPLE:\n", " ".join(txt.split())[:500])
        await b.close()

asyncio.run(probe(sys.argv[1]))
