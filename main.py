import os
import asyncio
import datetime
import pytz
import re
import discord
import subprocess
import sys
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

class MenuCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_posted_date = None
        self.daily_check.start()
        print("✅ [Cog] MenuCog initialized.")

    def cog_unload(self):
        self.daily_check.cancel()

    @tasks.loop(minutes=1)
    async def daily_check(self):
        now = datetime.datetime.now(TIMEZONE)
        if now.weekday() >= 5: return 
        
        if now.hour == TARGET_HOUR and now.minute == 0:
            today_str = now.strftime("%Y-%m-%d")
            if self.last_posted_date != today_str:
                print(f"⏰ [Schedule] Auto-posting for {today_str}...")
                await self.process_canva_menu()
                self.last_posted_date = today_str

    @commands.command(name="postnow")
    async def postnow(self, ctx):
        """Manually trigger the Canva menu process."""
        print(f"📢 [Command] !postnow triggered.")
        await self.process_canva_menu(ctx)

    async def process_canva_menu(self, ctx=None):
        target = ctx if ctx else self.bot.get_channel(CHANNEL_ID)
        if not target:
            print(f"❌ [Error] Channel {CHANNEL_ID} not found.")
            return

        status_msg = None
        if ctx: status_msg = await ctx.send("⏳ **Accessing Canva...** (Wait ~45s for rendering)")

        try:
            print(f"🌐 [Browser] Starting Playwright session...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1280, "height": 1800})
                
                print(f"🔗 [Browser] Navigating to URL...")
                try:
                    # Using 'domcontentloaded' and a longer timeout to avoid Canva specific stalls
                    await page.goto(CANVA_URL, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    print(f"⚠️ [Browser] Navigation warning: {e}. Proceeding with rendering...")

                # Crucial: Fixed wait for heavy Canva JS components to finish loading/animating
                print("⏳ [Browser] Waiting for poster content to render...")
                await asyncio.sleep(25) 
                
                screenshot_path = "menu_screenshot.png"
                await page.screenshot(path=screenshot_path)
                await browser.close()
                print("📸 [Browser] Screenshot captured successfully.")

            print("🔍 [OCR] Analyzing screenshot...")
            img = Image.open(screenshot_path)
            text = pytesseract.image_to_string(img)
            
            dish_name = "Today's Special"
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            for i, line in enumerate(lines):
                if any(k in line.upper() for k in ["SPECIAL", "DISH", "ENTREE", "TODAY"]):
                    extracted = line.split(":")[-1].strip()
                    dish_name = extracted if extracted else (lines[i+1] if i+1 < len(lines) else "Special")
                    break

            file = discord.File(screenshot_path, filename="menu.png")
            embed = discord.Embed(
                title="🍽 Dining Hall Special",
                color=discord.Color.blue(),
                description=f"Automated update for **{datetime.datetime.now(TIMEZONE).strftime('%A, %b %d')}**",
                timestamp=datetime.datetime.now()
            )
            embed.add_field(name="**Featured Menu**", value=dish_name[:256], inline=False)
            embed.set_image(url="attachment://menu.png")
            embed.set_footer(text="Render Infrastructure • Senior Bot Architect")

            if status_msg: await status_msg.delete()
            
            if ctx: await ctx.send(embed=embed, file=file)
            else: await target.send(embed=embed, file=file)
            print("✅ [Success] Post sent.")

        except Exception as e:
            print(f"❌ [Exception] {e}")
            err_text = f"⚠️ **Processing Error:**\n```{str(e)[:400]}```"
            if status_msg: await status_msg.edit(content=err_text)
            elif ctx: await ctx.send(err_text)

class CanvaMenuBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.add_cog(MenuCog(self))
        # Health check for Render
        app = web.Application()
        app.router.add_get('/', lambda r: web.Response(text="Bot is online."))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', '8080')))
        await site.start()

    async def on_ready(self):
        print(f"🤖 Bot online as {self.user}")
        print(f"📋 Commands: {[c.name for c in self.commands]}")

if __name__ == "__main__":
    if not TOKEN or not CHANNEL_ID:
        print("❌ CRITICAL: Missing ENV VARS.")
        sys.exit(1)
    bot = CanvaMenuBot()
    bot.run(TOKEN)
