import os
import asyncio
import datetime
import pytz
import re
import discord
import subprocess
from discord.ext import tasks, commands
from playwright.async_api import async_playwright
from aiohttp import web
try:
    from PIL import Image
    import pytesseract
except ImportError:
    print("Missing OCR dependencies.")

# --- CONFIGURATION ---
TOKEN = os.environ.get('DISCORD_TOKEN')
CHANNEL_ID = int(os.environ.get('CHANNEL_ID', '0'))
CANVA_URL = "https://www.canva.com/design/DAFpwTJjsUs/8E5-E_qF_z__oZcYPRK1vA/view?utm_content=DAFpwTJjsUs&utm_campaign=designshare&utm_medium=link2&utm_source=uniquelinks&utlId=h4292316f69"
TIMEZONE = pytz.timezone("America/Los_Angeles")
TARGET_HOUR = 17  # 5:00 PM
# ---------------------

class CanvaMenuBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.last_posted_date = None

    async def setup_hook(self):
        # Verify Tesseract is installed for debugging
        try:
            version = subprocess.check_output(["tesseract", "--version"]).decode()
            print(f"OCR Engine Ready: {version.splitlines()[0]}")
        except:
            print("WARNING: Tesseract not found in PATH")
            
        self.daily_check.start()
        server = web.Server(self.handle_health_check)
        runner = web.ServerRunner(server)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', '8080')))
        await site.start()
        print(f"Bot started. Scheduled for {TARGET_HOUR}:00 {TIMEZONE.zone}")

    async def handle_health_check(self, request):
        return web.Response(text="Bot is alive and monitoring Canva.")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")

    @tasks.loop(minutes=1)
    async def daily_check(self):
        now = datetime.datetime.now(TIMEZONE)
        if now.weekday() >= 5: return
        if now.hour == TARGET_HOUR and now.minute == 0:
            today_str = now.strftime("%Y-%m-%d")
            if self.last_posted_date != today_str:
                await self.process_canva_menu()
                self.last_posted_date = today_str

    async def process_canva_menu(self):
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            print("Error: Could not find channel.")
            return

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1280, "height": 1800})
                await page.goto(CANVA_URL, wait_until="networkidle")
                await asyncio.sleep(7) 
                
                screenshot_path = "menu_screenshot.png"
                await page.screenshot(path=screenshot_path)
                await browser.close()

            text = pytesseract.image_to_string(Image.open(screenshot_path))
            dish_match = re.search(r"(?:Special|Today|Dish):?\s*(.*)", text, re.IGNORECASE)
            ingredients_match = re.search(r"(?:Ingredients|Contains):?\s*(.*)", text, re.IGNORECASE | re.DOTALL)
            
            dish_name = dish_match.group(1).strip() if dish_match else "Daily Special"
            ingredients_list = ingredients_match.group(1).strip() if ingredients_match else "Refer to attached image"

            file = discord.File(screenshot_path, filename="menu.png")
            embed = discord.Embed(
                title="🍽 Dining Hall Special",
                color=discord.Color.gold(),
                timestamp=datetime.datetime.now()
            )
            embed.add_field(name="**Dish**", value=dish_name, inline=False)
            embed.add_field(name="**Ingredients**", value=ingredients_list, inline=False)
            embed.set_image(url="attachment://menu.png")
            embed.set_footer(text="Automatic Update • Render Cloud")

            await channel.send(embed=embed, file=file)
            print("Successfully posted menu update.")

        except Exception as e:
            print(f"Error: {e}")
            if channel:
                await channel.send(f"⚠️ **Error:** Failed to process menu.\n`{e}`")

if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable not found!")
    else:
        bot = CanvaMenuBot()
        bot.run(TOKEN)
