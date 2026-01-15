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
        print("✅ [Cog] MenuCog initialized and background task started.")

    def cog_unload(self):
        self.daily_check.cancel()

    @tasks.loop(minutes=1)
    async def daily_check(self):
        now = datetime.datetime.now(TIMEZONE)
        if now.weekday() >= 5: return # Skip weekends
        
        if now.hour == TARGET_HOUR and now.minute == 0:
            today_str = now.strftime("%Y-%m-%d")
            if self.last_posted_date != today_str:
                print(f"⏰ [Schedule] Time reached ({TARGET_HOUR}:00). Running auto-post...")
                await self.process_canva_menu()
                self.last_posted_date = today_str

    @commands.command(name="postnow")
    async def postnow(self, ctx):
        """Manually trigger the Canva menu process."""
        print(f"📢 [Command] !postnow requested by {ctx.author}")
        await self.process_canva_menu(ctx)

    async def process_canva_menu(self, ctx=None):
        target = ctx if ctx else self.bot.get_channel(CHANNEL_ID)
        if not target:
            print(f"❌ [Error] Channel ID {CHANNEL_ID} not found in bot cache.")
            if ctx: await ctx.send(f"❌ Error: Cannot find channel {CHANNEL_ID}. Bot might lack permissions.")
            return

        status_msg = None
        if ctx: status_msg = await ctx.send("⏳ **Processing Canva Poster...** (This takes ~30 seconds)")

        try:
            print(f"🌐 [Browser] Launching Playwright for {CANVA_URL}")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1280, "height": 1800})
                
                await page.goto(CANVA_URL, wait_until="networkidle")
                print("📄 [Browser] Page loaded. Waiting for Canva JS rendering...")
                await asyncio.sleep(15) # Wait for animations
                
                screenshot_path = "menu_screenshot.png"
                await page.screenshot(path=screenshot_path)
                await browser.close()
                print("📸 [Browser] Screenshot saved.")

            print("🔍 [OCR] Extracting text...")
            img = Image.open(screenshot_path)
            text = pytesseract.image_to_string(img)
            
            # Simplified Parsing Logic
            dish_name = "Daily Special"
            details = "Check the attached poster for today's selection."
            
            # Logic: Split by lines and look for key phrases
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            for i, line in enumerate(lines):
                if any(k in line.upper() for k in ["SPECIAL", "DISH", "ENTREE", "TODAY"]):
                    dish_name = line.split(":")[-1].strip() or (lines[i+1] if i+1 < len(lines) else "Special")
                    break

            file = discord.File(screenshot_path, filename="menu.png")
            embed = discord.Embed(
                title="🍽 Dining Hall Special",
                color=discord.Color.from_rgb(0, 102, 204),
                description=f"Update for **{datetime.datetime.now(TIMEZONE).strftime('%A, %b %d')}**",
                timestamp=datetime.datetime.now()
            )
            embed.add_field(name="**Featured Dish**", value=dish_name[:256], inline=False)
            embed.add_field(name="**OCR Insights**", value=details[:1024], inline=False)
            embed.set_image(url="attachment://menu.png")
            embed.set_footer(text="Automated Architecture • Render Cloud")

            if status_msg: await status_msg.delete()
            
            if ctx: await ctx.send(embed=embed, file=file)
            else: await target.send(embed=embed, file=file)
            print("✅ [Success] Menu posted to Discord.")

        except Exception as e:
            print(f"❌ [Exception] {e}")
            if status_msg: await status_msg.edit(content=f"⚠️ **Error Processing Canva:**\n```{str(e)[:400]}```")

class CanvaMenuBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True # CRITICAL for commands to work
        super().__init__(command_prefix="!", intents=intents, help_command=commands.DefaultHelpCommand())

    async def setup_hook(self):
        # Register the Cog
        print("🛠 [Setup] Loading Cogs...")
        await self.add_cog(MenuCog(self))
        
        # Verify OCR binaries
        try:
            v = subprocess.check_output(["tesseract", "--version"]).decode().splitlines()[0]
            print(f"✅ [System] {v}")
        except Exception:
            print("❌ [System] Tesseract OCR not found!")

        # Start health check server for Render
        app = web.Application()
        app.router.add_get('/', lambda r: web.Response(text="OK"))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', '8080')))
        await site.start()
        print(f"🚀 [Health] Web server live on port {os.environ.get('PORT', '8080')}")

    async def on_ready(self):
        print(f"🤖 [Status] Logged in as {self.user} (ID: {self.user.id})")
        print(f"📋 [System] Registered Commands: {[c.name for c in self.commands]}")
        print(f"🔑 [System] Current Prefix: '{self.command_prefix}'")
        if not self.commands:
            print("⚠️ [Warning] No commands found! Cog registration might have failed.")

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            print(f"❓ [Warning] Unknown command attempted: '{ctx.message.content}' by {ctx.author}")
            # Do not send message to Discord to avoid spamming on typos, 
            # but keep it in Render logs for debugging.
        else:
            print(f"🔥 [Error] {error}")

if __name__ == "__main__":
    if not TOKEN:
        print("❌ CRITICAL: DISCORD_TOKEN is missing in Environment Variables!")
        sys.exit(1)
    if not CHANNEL_ID:
        print("❌ CRITICAL: CHANNEL_ID is missing in Environment Variables!")
        sys.exit(1)
        
    bot = CanvaMenuBot()
    bot.run(TOKEN)
