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
            print(f"✅ OCR Engine Ready: {version.splitlines()[0]}")
        except Exception as e:
            print(f"❌ WARNING: Tesseract not found: {e}")
            
        self.daily_check.start()
        
        # Simple health check server
        app = web.Application()
        app.router.add_get('/', self.handle_health_check)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', '8080')))
        await site.start()
        print(f"🚀 Health check server running on port {os.environ.get('PORT', '8080')}")
        print(f"📅 Schedule: Bot will post daily at {TARGET_HOUR}:00 {TIMEZONE.zone}")

    async def handle_health_check(self, request):
        return web.Response(text="Bot is alive and monitoring Canva.")

    async def on_ready(self):
        print(f"🤖 Logged in as {self.user} (ID: {self.user.id})")
        print("💡 Tip: Type !postnow in your Discord channel to test the bot immediately.")

    @tasks.loop(minutes=1)
    async def daily_check(self):
        now = datetime.datetime.now(TIMEZONE)
        # Skip weekends (Saturday=5, Sunday=6)
        if now.weekday() >= 5: return
        
        if now.hour == TARGET_HOUR and now.minute == 0:
            today_str = now.strftime("%Y-%m-%d")
            if self.last_posted_date != today_str:
                print(f"⏰ Scheduled time reached ({TARGET_HOUR}:00). Starting menu process...")
                await self.process_canva_menu()
                self.last_posted_date = today_str

    async def process_canva_menu(self, ctx=None):
        target = ctx if ctx else self.get_channel(CHANNEL_ID)
        if not target:
            print("❌ Error: Could not find target channel. Check your CHANNEL_ID.")
            if ctx: await ctx.send("❌ Error: Channel ID configuration is incorrect.")
            return

        status_msg = None
        if ctx: status_msg = await ctx.send("⏳ *Starting Canva processing...*")

        try:
            print(f"🌐 Launching browser for: {CANVA_URL}")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1280, "height": 1800})
                
                print("📄 Navigating to Canva page...")
                await page.goto(CANVA_URL, wait_until="networkidle")
                
                print("Wait 10s for Canva animations to settle...")
                await asyncio.sleep(10) 
                
                screenshot_path = "menu_screenshot.png"
                print("📸 Taking screenshot...")
                await page.screenshot(path=screenshot_path)
                await browser.close()

            print("🔍 Starting OCR Analysis...")
            text = pytesseract.image_to_string(Image.open(screenshot_path))
            print(f"📝 Raw OCR Text Extracted: {len(text)} characters")

            # Simple regex to find content
            dish_match = re.search(r"(?:Special|Today|Dish|Entree):?\s*(.*)", text, re.IGNORECASE)
            ingredients_match = re.search(r"(?:Ingredients|Contains|With):?\s*(.*)", text, re.IGNORECASE | re.DOTALL)
            
            dish_name = dish_match.group(1).strip() if dish_match else "Daily Special"
            ingredients_list = ingredients_match.group(1).strip() if ingredients_match else "See attached menu image for details."

            print(f"🎯 Parsing complete. Dish: {dish_name}")

            file = discord.File(screenshot_path, filename="menu.png")
            embed = discord.Embed(
                title="🍽 Dining Hall Special",
                color=discord.Color.gold(),
                description=f"Automated update for {datetime.datetime.now(TIMEZONE).strftime('%A, %b %d')}",
                timestamp=datetime.datetime.now()
            )
            embed.add_field(name="**Dish Name**", value=dish_name, inline=False)
            embed.add_field(name="**Details**", value=ingredients_list[:1024], inline=False)
            embed.set_image(url="attachment://menu.png")
            embed.set_footer(text="Verified via Canva OCR • Render Cloud")

            if status_msg: await status_msg.delete()
            
            if ctx:
                await ctx.send(embed=embed, file=file)
            else:
                await target.send(embed=embed, file=file)
                
            print("✅ Successfully posted to Discord.")

        except Exception as e:
            print(f"❌ ERROR in process_canva_menu: {e}")
            error_text = f"⚠️ **Error Processing Menu**\n```{str(e)[:500]}```"
            if ctx: await ctx.send(error_text)
            else: await target.send(error_text)

    @commands.command(name="postnow")
    async def postnow(self, ctx):
        """Manually triggers the Canva menu process."""
        print(f"📢 Manual trigger received from {ctx.author}")
        await self.process_canva_menu(ctx)

if __name__ == "__main__":
    if not TOKEN:
        print("❌ CRITICAL ERROR: DISCORD_TOKEN environment variable is missing!")
    elif not CHANNEL_ID:
        print("❌ CRITICAL ERROR: CHANNEL_ID environment variable is missing!")
    else:
        bot = CanvaMenuBot()
        bot.run(TOKEN)
