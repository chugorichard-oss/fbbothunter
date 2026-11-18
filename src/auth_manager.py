import asyncio
import os
from playwright.async_api import async_playwright

STATE_FILE = os.path.join(os.path.dirname(__file__), "auth_state.json")

async def generate_session():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="es-LA",
            timezone_id="America/La_Paz"
        )
        
        page = await context.new_page()
        await page.goto("https://www.facebook.com/")
        
        print("=" * 60)
        print("👉 Inicia sesión manualmente en la ventana que se abrió en Windows.")
        print("👉 Una vez que veas tu muro de inicio, vuelve aquí y presiona ENTER.")
        print("=" * 60)
        
        await asyncio.to_thread(input, "Presiona ENTER para guardar la sesión...")
        
        await context.storage_state(path=STATE_FILE)
        print(f"✅ Sesión guardada exitosamente en: {STATE_FILE}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(generate_session())
