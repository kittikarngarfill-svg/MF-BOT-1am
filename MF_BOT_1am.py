# MF_BOT_1am.py — รวมฟีเจอร์เดิม + เสียงนิ่งขึ้น + กันลงทะเบียนซ้ำ + ready สำหรับ Docker/Web
# ฟีเจอร์:
# - ปุ่ม Alarm DM ทั้ง Role
# - คำสั่ง !ปุ่ม ส่งปุ่ม Alarm
# - คำสั่ง !เช็คชื่อ โพสต์เช็คอินพร้อม reaction ในห้องที่กำหนด
# - Welcome/Leave Embed
# - ลงทะเบียน (Modal: ชื่อเล่น/อายุ) → เปลี่ยนนิคเนม + กันลงทะเบียนซ้ำ (บันทึกลงไฟล์ JSON)
# - สถานะออนไลน์ (แสดงจำนวนสมาชิกออนไลน์)
# - ระบบเสียง: เข้าห้อง VC ที่กำหนด, TTS เข้า/ออก/Deaf, กัน connect ซ้อน, ตัดออกเมื่อไม่มีคน
# - keep_alive (ถ้ามีไฟล์ keep_alive.py)

import os
import sys
import json
import signal
import traceback
import asyncio
import shutil
import datetime
import aiohttp

from dotenv import load_dotenv

# ใช้ discord.py (official)
import discord
from discord.ext import commands, tasks
from discord.utils import get

# ---------------- keep_alive (optional) ----------------
try:
    from keep_alive import keep_alive
    HAS_KEEP_ALIVE = True
except Exception:
    HAS_KEEP_ALIVE = False
    def keep_alive():
        pass

# ---------------- ENV loader ----------------
load_dotenv()

def require_env(name, cast=str, allow_empty=False, default_sentinel=object()):
    v = os.getenv(name)
    if v is None:
        if default_sentinel is not object():
            return default_sentinel
        print(f"[FATAL] Missing ENV: {name}", flush=True)
        sys.exit(1)
    if not allow_empty and str(v).strip() == "":
        print(f"[FATAL] Empty ENV: {name}", flush=True)
        sys.exit(1)
    try:
        return cast(v)
    except Exception as e:
        print(f"[FATAL] Bad ENV type for {name}: {v} ({e})", flush=True)
        sys.exit(1)

TOKEN = require_env("DISCORD_TOKEN", str)
GUILD_ID = require_env("GUILD_ID", int)
VC_CHANNEL_ID = require_env("VC_CHANNEL_ID", int)
TEXT_CHANNEL_ID = require_env("TEXT_CHANNEL_ID", int)
STATUS_UPDATE_INTERVAL = int(os.getenv("STATUS_UPDATE_INTERVAL", "30"))

# ค่าเสริม (แก้หรือใส่ใน .env ได้)
ROLE_ID = int(os.getenv("ROLE_ID", "1372176652989239336"))
BOT_CHANNEL_ID = int(os.getenv("BOT_CHANNEL_ID", "1403316515956064327"))
CHECKRAID_CHANNEL_ID = int(os.getenv("CHECKRAID_CHANNEL_ID", "1385971877079679006"))
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "1342083527067304030"))
GOODBYE_CHANNEL_ID = int(os.getenv("GOODBYE_CHANNEL_ID", "1342083527067304030"))

ENABLE_VOICE = os.getenv("ENABLE_VOICE", "1") == "1"

print(f"[BOOT] ENV ok | guild={GUILD_ID} vc={VC_CHANNEL_ID} text={TEXT_CHANNEL_ID} "
      f"role={ROLE_ID} checkraid={CHECKRAID_CHANNEL_ID} voice={ENABLE_VOICE}", flush=True)

# ---------------- Intents / Bot ----------------
intents = discord.Intents.all()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- Signal & on_error hooks ----------------
def _graceful_shutdown(signum, frame):
    print(f"[SIGNAL] Received {signum} -> shutting down", flush=True)
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(bot.close())
    except Exception as e:
        print(f"[SIGNAL] close failed: {e}", flush=True)

for s in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(s, _graceful_shutdown)
    except Exception:
        pass

@bot.event
async def on_error(event_method, *args, **kwargs):
    print(f"[on_error] in {event_method}", flush=True)
    traceback.print_exc()

# ---------------- Voice prerequisites ----------------
FFMPEG_OK = shutil.which("ffmpeg") is not None
if ENABLE_VOICE:
    if not FFMPEG_OK:
        print("[WARN] ffmpeg not found - เสียงจะเล่นไม่ได้", flush=True)
    try:
        if not discord.opus.is_loaded():
            # ใน Docker Debian/Ubuntu ไลบรารีชื่อ libopus.so.0
            discord.opus.load_opus("libopus.so.0")
        print("[OK] Opus loaded", flush=True)
    except Exception as e:
        print(f"[ERROR] load Opus failed: {e}", flush=True)

voice_connect_lock = asyncio.Lock()
voice_client: discord.VoiceClient | None = None
joined_users = set()
last_voice_states = {}

def non_bot_count(ch: discord.VoiceChannel) -> int:
    return sum(1 for m in ch.members if not m.bot)

def tts_url(text: str) -> str:
    # Google TTS แบบง่าย (สำหรับทดสอบ)
    return f"https://translate.google.com/translate_tts?ie=UTF-8&q={text}&tl=th&client=tw-ob"

async def play_tts(vc: discord.VoiceClient | None, text: str):
    if not ENABLE_VOICE:
        return
    if not vc or not vc.is_connected():
        return
    if not FFMPEG_OK:
        print("[WARN] Skip TTS: ffmpeg not installed", flush=True)
        return

    url = tts_url(text)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"Failed to get TTS: {resp.status}", flush=True)
                    return
                with open("tts.mp3", "wb") as f:
                    f.write(await resp.read())
    except Exception as e:
        print(f"[ERROR] TTS fetch failed: {e}", flush=True)
        return

    try:
        if not vc.is_playing():
            vc.play(discord.FFmpegPCMAudio("tts.mp3"))
            while vc.is_playing():
                await asyncio.sleep(0.3)
    except Exception as e:
        print(f"[ERROR] ffmpeg/voice play failed: {e}", flush=True)

# ---------------- Registration (one-time) ----------------
REG_FILE = "registered_users.json"
def _load_registered() -> set[int]:
    try:
        with open(REG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(int(x) for x in data)
    except Exception:
        return set()

def _save_registered(s: set[int]):
    try:
        with open(REG_FILE, "w", encoding="utf-8") as f:
            json.dump(list(s), f)
    except Exception as e:
        print(f"[WARN] Save registered failed: {e}", flush=True)

registered_users = _load_registered()

class RegisterModal(discord.ui.Modal, title="ลงทะเบียนสมาชิก 1am SCUM TEAM"):
    nickname = discord.ui.TextInput(label="ชื่อเล่น", placeholder="ใส่ชื่อเล่นของคุณ", max_length=32)
    age = discord.ui.TextInput(label="อายุ", placeholder="ใส่อายุของคุณ", max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if user_id in registered_users:
            await interaction.response.send_message("❌ คุณลงทะเบียนไปแล้ว ไม่สามารถลงทะเบียนซ้ำได้ครับ", ephemeral=True)
            return

        member = interaction.user
        new_nick = f"{self.nickname.value} ({self.age.value})"

        try:
            # ตรวจสิทธิ์เปลี่ยนชื่อ + ลำดับ role
            me = interaction.guild.get_member(bot.user.id) or interaction.guild.me
            can_manage = me.guild_permissions.manage_nicknames if me else False
            bot_top_pos = me.top_role.position if me and me.top_role else -1
            target_top_pos = member.top_role.position if member.top_role else -1

            if not can_manage or bot_top_pos <= target_top_pos or member == interaction.guild.owner:
                await interaction.response.send_message(
                    f"✅ ได้รับข้อมูลแล้ว\nชื่อเล่น: {self.nickname.value}\nอายุ: {self.age.value}\n"
                    f"⚠️ แต่บอทไม่มีสิทธิ์/ลำดับ role ไม่พอในการเปลี่ยนชื่อให้คุณ\n"
                    f"กรุณาให้แอดมินย้าย role ของบอทไว้สูงกว่า หรือให้สิทธิ์ Manage Nicknames",
                    ephemeral=True
                )
                # กันลงทะเบียนซ้ำ
                registered_users.add(user_id)
                _save_registered(registered_users)
                return

            await member.edit(nick=new_nick)
            registered_users.add(user_id)
            _save_registered(registered_users)

            await interaction.response.send_message(
                f"✅ ลงทะเบียนสำเร็จ!\nชื่อเล่นถูกเปลี่ยนเป็น `{new_nick}`", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ บอทไม่มีสิทธิ์เปลี่ยนชื่อคุณ!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

class RegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ลงทะเบียน", style=discord.ButtonStyle.success)
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in registered_users:
            await interaction.response.send_message("❌ คุณลงทะเบียนไปแล้ว ไม่สามารถลงทะเบียนซ้ำได้ครับ", ephemeral=True)
            return
        await interaction.response.send_modal(RegisterModal())

# ---------------- Buttons: Alarm to Role ----------------
class RoleMessageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Alarm", style=discord.ButtonStyle.danger, emoji="🚨")
    async def alarm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_to_role(interaction, "📢 นี่คือข้อความจาก MF_BOT จ้า! ขอความร่วมมือเข้าดิสด่วนน !!")

    async def send_to_role(self, interaction: discord.Interaction, message_text: str):
        role = interaction.guild.get_role(ROLE_ID)
        if not role:
            await interaction.response.send_message("❌ ไม่พบบทบาทนี้", ephemeral=True)
            return

        sent = 0
        for member in role.members:
            try:
                if not member.bot:
                    await member.send(message_text)
                    sent += 1
                    await asyncio.sleep(0.5)  # กัน rate limit
            except:
                pass
        await interaction.response.send_message(f"📨 ส่งข้อความให้ {sent} คนแล้ว", ephemeral=True)

# ---------------- Commands ----------------
@bot.command(name="ปุ่ม")
async def cmd_buttons(ctx: commands.Context):
    if ctx.channel.id != BOT_CHANNEL_ID:
        await ctx.send("❌ ใช้คำสั่งนี้ได้เฉพาะในห้อง BOT เท่านั้น")
        return

    embed = discord.Embed(
        title="🛠️ MF_BOT Panel",
        description="ใช้ปุ่มด้านล่างเพื่อเรียกเตือนสมาชิกกลุ่มเป้าหมาย",
        color=0xFFD700
    )
    embed.set_thumbnail(url="https://i.ibb.co/3kZ0xFq/mf-logo.png")
    embed.set_footer(text="MF_BOT • Control Panel")
    await ctx.send(embed=embed, view=RoleMessageView())

@bot.command(name="เช็คชื่อ")
async def cmd_checkin(ctx: commands.Context):
    if ctx.channel.id != CHECKRAID_CHANNEL_ID:
        await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะในห้องเช็คชื่อที่กำหนดเท่านั้น!")
        return
    today = datetime.datetime.now().strftime("%d/%m/%y")
    role_mention = f"<@&{ROLE_ID}>"
    embed = discord.Embed(
        title="🌅 เช็คชื่อ Raid/Protect",
        description=f"วันที่ {today} \n{role_mention} โปรดเช็คชื่อด้วยปุ่ม Reaction ด้านล่าง",
        color=0x00C853
    )
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

@bot.command(name="ลงทะเบียน")
async def cmd_register(ctx: commands.Context):
    embed = discord.Embed(
        title="📋 ลงทะเบียนสมาชิก",
        description="กดปุ่มด้านล่างเพื่อเปิดฟอร์มกรอกชื่อเล่นและอายุ\n(ลงทะเบียนได้ครั้งเดียว)",
        color=0x42A5F5
    )
    embed.set_footer(text="MF_BOT • Registration")
    await ctx.send(embed=embed, view=RegisterView())

@bot.command()
async def ping(ctx: commands.Context):
    await ctx.send("pong!")

# ---------------- Member join/leave ----------------
@bot.event
async def on_member_join(member: discord.Member):
    print(f"📥 ตรวจพบ {member} เข้าร่วม")
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel and isinstance(channel, discord.TextChannel):
        embed = discord.Embed(
            title="🥇 ยินดีต้อนรับเข้าสู่ 1am SCUM TEAM 🥇",
            description=f"🙏 สวัสดีจ้า {member.mention}\nมานัวกับเราได้เล๊ย!",
            color=0xFFD700
        )
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        embed.set_image(url="https://i.ibb.co/3kZ0xFq/mf-logo.png")
        embed.set_footer(text="MF_BOT • ระบบต้อนรับ")
        await channel.send(embed=embed)

@bot.event
async def on_member_remove(member: discord.Member):
    channel = bot.get_channel(GOODBYE_CHANNEL_ID)
    if channel and isinstance(channel, discord.TextChannel):
        embed = discord.Embed(
            title="😢 สมาชิกออกจากเซิร์ฟเวอร์",
            description=f"{member.name} ได้ออกจากเซิร์ฟเวอร์แล้ว",
            color=0xB0BEC5
        )
        await channel.send(embed=embed)

# ---------------- Presence / Ready ----------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})", flush=True)
    try:
        update_status.start()
    except RuntimeError:
        pass

@tasks.loop(seconds=STATUS_UPDATE_INTERVAL)
async def update_status():
    guild = bot.get_guild(GUILD_ID)
    if guild:
        online_members = [m for m in guild.members if m.status != discord.Status.offline and not m.bot]
        activity = discord.Game(name=f"สมาชิกออนไลน์ {len(online_members)} คน")
        await bot.change_presence(status=discord.Status.online, activity=activity)

@bot.event
async def on_disconnect():
    print("Bot disconnected! (gateway) — Discord side", flush=True)

# ---------------- Voice state (เสถียรขึ้น) ----------------
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if not ENABLE_VOICE:
        return
    if member.bot:
        return

    voice_channel = bot.get_channel(VC_CHANNEL_ID)
    if not isinstance(voice_channel, discord.VoiceChannel):
        return

    global voice_client

    try:
        # sync ปัจจุบัน
        vc_now = discord.utils.get(bot.voice_clients, guild=member.guild)
        if vc_now is not None:
            voice_client = vc_now

        # ถ้าไม่มี non-bot อยู่เลย → ถอดบอทออก
        if non_bot_count(voice_channel) == 0:
            if voice_client and voice_client.is_connected():
                await asyncio.sleep(5)
                if non_bot_count(voice_channel) == 0:
                    await voice_client.disconnect(force=True)
                    voice_client = None
                    print("Bot ออกจากห้องเพราะไม่มีใครอยู่", flush=True)
            return

        # มีคนแล้วแต่ยังไม่ต่อ → ต่อ โดยกันซ้อน
        if voice_client is None or not voice_client.is_connected():
            async with voice_connect_lock:
                vc_now = discord.utils.get(bot.voice_clients, guild=member.guild)
                if vc_now is None or not vc_now.is_connected():
                    print("กำลังเชื่อมต่อเข้าห้องเสียง...", flush=True)
                    try:
                        voice_client = await voice_channel.connect(reconnect=False)
                        print("เชื่อมต่อห้องเสียงแล้ว", flush=True)
                    except Exception as e:
                        print(f"[ERROR] connect voice failed: {e}", flush=True)
                        return

        # แจ้งเข้า/ออก
        if after.channel == voice_channel and before.channel != voice_channel:
            if member.id not in joined_users:
                joined_users.add(member.id)
                await play_tts(voice_client, f"{member.display_name} เข้ามาแล้วจ้า")
        elif before.channel == voice_channel and after.channel != voice_channel:
            if member.id in joined_users:
                joined_users.remove(member.id)
                await play_tts(voice_client, f"{member.display_name} ออกไปแล้วจ้า")

        # เดฟ/อันเดฟ
        if before.self_deaf != after.self_deaf:
            if after.self_deaf:
                await play_tts(voice_client, f"{member.display_name} ปิดหูทำไม")
            else:
                await play_tts(voice_client, f"{member.display_name} เปิดหูแล้วจ้า")

        last_voice_states[member.id] = after

    except AttributeError as e:
        print(f"[ERROR] on_voice_state_update(AttributeError): {e}", flush=True)
        try:
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect(force=True)
        except Exception:
            pass
        voice_client = None
    except Exception as e:
        print(f"[ERROR] on_voice_state_update: {e}", flush=True)

# ---------------- Main ----------------
if __name__ == "__main__":
    if HAS_KEEP_ALIVE:
        keep_alive()
    try:
        print("[BOOT] starting bot.run()", flush=True)
        bot.run(TOKEN)
        print("[BOOT] bot.run() returned (client closed).", flush=True)
    except Exception as e:
        print("[FATAL] bot.run crashed:", e, flush=True)
        traceback.print_exc()
        sys.exit(1)