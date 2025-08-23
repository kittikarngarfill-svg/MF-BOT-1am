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
from zoneinfo import ZoneInfo
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

# ค่าเสริม (แก้/ใส่ใน .env ได้)
ROLE_ID = int(os.getenv("ROLE_ID", "1372176652989239336"))
BOT_CHANNEL_ID = int(os.getenv("BOT_CHANNEL_ID", "1403316515956064327"))
CHECKRAID_CHANNEL_ID = int(os.getenv("CHECKRAID_CHANNEL_ID", "1385971877079679006"))
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "1342083527067304030"))
GOODBYE_CHANNEL_ID = int(os.getenv("GOODBYE_CHANNEL_ID", "1342083527067304030"))
ENABLE_VOICE = os.getenv("ENABLE_VOICE", "1") == "1"
PANEL_TITLE = "🥇 1am SCUM TEAM 🥇"
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Bangkok"))
SUMMARY_HOUR = int(os.getenv("RAID_SUMMARY_HOUR", "19"))  # 19:00 ตามเวลาไทย

print(f"[BOOT] ENV ok | guild={GUILD_ID} vc={VC_CHANNEL_ID} text={TEXT_CHANNEL_ID} "
      f"role={ROLE_ID} checkraid={CHECKRAID_CHANNEL_ID} voice={ENABLE_VOICE}", flush=True)

# ---------------- Intents / Bot ----------------
intents = discord.Intents.all()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    intents=intents,
    case_insensitive=True
)

# ---------------- Util: datetime / roles ----------------
def fmt_tz(dt: datetime.datetime | None) -> str:
    """format เป็น Y-m-d H:M ที่โซน TZ"""
    if not dt:
        return "ไม่พบข้อมูล"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M")

def parse_iso_utc(s: str | None) -> datetime.datetime | None:
    if not s:
        return None
    try:
        # รองรับ ...Z และ offset
        s2 = s.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(s2)
    except Exception:
        return None

def roles_string(member: discord.Member, limit: int = 10) -> str:
    roles = [r for r in member.roles if r.name != "@everyone"]
    if not roles:
        return "ไม่มีบทบาท"
    names = [r.name for r in roles]
    if len(names) <= limit:
        return ", ".join(names)
    shown = ", ".join(names[:limit])
    return f"{shown} … (+{len(names)-limit})"

# ---------------- Signal & on_error hooks ----------------
def _graceful_shutdown(signum, frame):
    print(f"[SIGNAL] Received {signum} -> shutting down", flush=True)
    try:
        loop = getattr(bot, "loop", None)
        if loop and loop.is_running():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(bot.close()))
        else:
            raise RuntimeError("event loop not running")
    except Exception as e:
        print(f"[SIGNAL] close failed: {e}", flush=True)
        try:
            bot.close()
        except Exception:
            pass
        raise SystemExit(0)

for s in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(s, _graceful_shutdown)
    except Exception:
        pass

@bot.event
async def on_error(event_method, *args, **kwargs):
    print(f"[on_error] in {event_method}", flush=True)
    traceback.print_exc()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        return
    try:
        await ctx.send(f"❌ เกิดข้อผิดพลาด: `{type(error).__name__}` — {error}")
    except Exception:
        pass
    print(f"[CMD-ERROR] In {getattr(ctx, 'command', None)}: {repr(error)}", flush=True)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    try:
        print(f"[MSG] #{getattr(message.channel, 'name', '?')} <{message.author}>: {message.content}", flush=True)
    except Exception:
        pass
    await bot.process_commands(message)

# ---------------- Voice prerequisites ----------------
FFMPEG_OK = shutil.which("ffmpeg") is not None
if ENABLE_VOICE:
    if not FFMPEG_OK:
        print("[WARN] ffmpeg not found - เสียงจะเล่นไม่ได้", flush=True)
    try:
        if not discord.opus.is_loaded():
            discord.opus.load_opus("libopus.so.0")  # Debian/Ubuntu
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

# ---------------- Registration (JSON dict; อัปเดตได้) ----------------
REG_FILE = "registered_users.json"

def _load_registered() -> dict[int, dict]:
    try:
        with open(REG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # รองรับทั้งรูปแบบเก่า (list user_id) และใหม่ (dict)
        if isinstance(data, list):
            return {int(uid): {"nickname": None, "age": None, "updated_at": None} for uid in data}
        if isinstance(data, dict):
            return {int(k): v for k, v in data.items()}
        return {}
    except Exception:
        return {}

def _save_registered(d: dict[int, dict]):
    try:
        with open(REG_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in d.items()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Save registered failed: {e}", flush=True)

registered_users: dict[int, dict] = _load_registered()

class RegisterModal(discord.ui.Modal, title="ลงทะเบียนสมาชิก 1AM SCUM TEAM"):
    nickname = discord.ui.TextInput(label="ชื่อเล่น", placeholder="เช่น ม็อปแม็ป", max_length=32)
    age = discord.ui.TextInput(label="อายุ (ตัวเลข)", placeholder="เช่น 49", max_length=3)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # กันกดซ้ำ: ลงทะเบียนได้ครั้งเดียว
        row = registered_users.get(interaction.user.id)
        if row and row.get("nickname"):
            await interaction.response.send_message(
                "❌ คุณได้ลงทะเบียนไปแล้ว **ลงทะเบียนได้ครั้งเดียวต่อคน**",
                ephemeral=True
            )
            return

        # ตรวจสอบอายุให้เป็นตัวเลข 1–120
        try:
            age_val = int(str(self.age.value).strip())
            if not (1 <= age_val <= 120):
                raise ValueError
        except Exception:
            await interaction.response.send_message(
                "กรุณากรอก **อายุเป็นตัวเลข 1–120**",
                ephemeral=True
            )
            return

        member = interaction.user
        new_nick = f"{self.nickname.value} ({age_val})"

        # เช็คสิทธิ์แก้ชื่อ
        me = interaction.guild.get_member(bot.user.id) or interaction.guild.me
        can_manage = bool(me and getattr(me, "guild_permissions", None) and me.guild_permissions.manage_nicknames)
        bot_top_pos = (me.top_role.position if (me and me.top_role) else 0)
        target_top_pos = (member.top_role.position if member.top_role else 0)

        changed_nick = False
        if can_manage and bot_top_pos > target_top_pos and member != interaction.guild.owner:
            try:
                await member.edit(nick=new_nick)
                changed_nick = True
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[REG] edit nick error: {e}", flush=True)

        # บันทึกครั้งแรกเท่านั้น (one-time)
        registered_users[member.id] = {
            "nickname": str(self.nickname.value).strip(),
            "age": age_val,
            "updated_at": datetime.datetime.utcnow().isoformat()
        }
        _save_registered(registered_users)

        # สรุปผล (สไตล์เหมือนรูป)
        if changed_nick:
            msg = (
                "✅ **ลงทะเบียนสำเร็จ!**\n"
                f"ชื่อ:  `{self.nickname.value}`   │   อายุ:  `{age_val}`   →  **เปลี่ยนชื่อเป็น**  `{new_nick}`"
            )
        else:
            msg = (
                "✅ **ได้รับข้อมูลแล้ว**\n"
                f"ชื่อ:  `{self.nickname.value}`   │   อายุ:  `{age_val}`\n"
                "⚠️ แต่บอทไม่มีสิทธิ์/ลำดับ role ไม่พอในการเปลี่ยนชื่อให้คุณ"
            )
        await interaction.response.send_message(msg, ephemeral=True)


def make_register_panel_embed() -> discord.Embed:
    # ใช้รูปแบบข้อความให้เหมือนภาพตัวอย่าง
    desc = (
        "📝 **ลงทะเบียนสมาชิก 1AM SCUM TEAM** 📝\n\n"
        "คลิกปุ่ม **ลงทะเบียน** เพื่อกรอกชื่อเล่นและอายุ\n\n"
        "**เงื่อนไข**\n"
        "• ลงทะเบียนได้ **ครั้งเดียวต่อคน**\n"
        "• ชื่อจะถูกตั้งเป็นรูปแบบ  `ชื่อเล่น  (อายุ)`\n"
        "• หากบอทไม่สามารถเปลี่ยนชื่อได้ แสดงว่า **บอทถูกจำกัดสิทธิ์**\n\n"
        "**วิธีใช้งาน**\n"
        "1) กดปุ่มด้านล่าง\n"
        "2) กรอก **ชื่อเล่น** และ **อายุ**\n"
        "3) กดส่ง แล้วรอสรุปผล\n\n"
        "**ตัวอย่างผลลัพธ์**\n"
        "ชื่อ:  `ม็อปแป็ป`   │   อายุ:  `49`   →  เปลี่ยนชื่อเป็น  `ม็อปแม็ป (49)`"
    )
    emb = discord.Embed(title=PANEL_TITLE, description=desc, color=0x2ecc71)
    emb.set_footer(text="MF_BOT • ระบบลงทะเบียน")
    return emb

def build_myinfo_embed(member: discord.Member, row: dict | None) -> discord.Embed:
    """สร้าง embed ข้อมูลสมาชิก: ชื่อเล่น/อายุ/วันที่เข้าดิสคอร์ด/วันที่ลงทะเบียน/บทบาท"""
    emb = discord.Embed(title="ข้อมูลลงทะเบียนของคุณ", color=0x3498db)
    nickname = row.get("nickname") if row else None
    age = row.get("age") if row else None
    reg_dt = parse_iso_utc(row.get("updated_at")) if row else None

    emb.add_field(name="ชื่อเล่น", value=nickname or "ยังไม่ลงทะเบียน")
    emb.add_field(name="อายุ", value=(str(age) if age is not None else "-"))
    emb.add_field(name="วันที่เข้าดิสคอร์ด", value=fmt_tz(member.joined_at), inline=False)
    emb.add_field(name="วันที่ลงทะเบียน", value=fmt_tz(reg_dt), inline=False)
    emb.add_field(name="บทบาทปัจจุบัน", value=roles_string(member), inline=False)
    emb.set_thumbnail(url=member.display_avatar.url)
    emb.set_footer(text="เวลาแสดงผลในเขตเวลา Asia/Bangkok")
    return emb


class RegisterView(discord.ui.View):
    """แสดงสองปุ่ม: 📝 ลงทะเบียน และ 👤 My Info"""
    def __init__(self):
        super().__init__(timeout=None)  # persistent

    @discord.ui.button(label="ลงทะเบียน", style=discord.ButtonStyle.success, emoji="📝", custom_id="reg_open_modal")
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ถ้าลงทะเบียนแล้ว -> ไม่ให้กดซ้ำ
        if interaction.user.id in registered_users and registered_users[interaction.user.id].get("nickname"):
            return await interaction.response.send_message(
                "❌ คุณได้ลงทะเบียนไปแล้ว **ลงทะเบียนได้ครั้งเดียวต่อคน**",
                ephemeral=True
            )
        await interaction.response.send_modal(RegisterModal())

    @discord.ui.button(label="My Info", style=discord.ButtonStyle.secondary, emoji="👤", custom_id="reg_myinfo_btn")
    async def myinfo(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = registered_users.get(interaction.user.id)
        emb = build_myinfo_embed(interaction.user, row)
        await interaction.response.send_message(embed=emb, ephemeral=True)

# ---------------- Raid Check state (JSON) ----------------
RAID_STATE_FILE = "raid_state.json"
def load_raid_state():
    try:
        with open(RAID_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"current": None}

def save_raid_state(state):
    try:
        with open(RAID_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"[WARN] save raid_state failed: {e}", flush=True)

raid_state = load_raid_state()
# raid_state = {"current": {"date":"YYYY-MM-DD","channel_id": int,"message_id": int,"summary_sent": bool}}

# ---------------- Raid Check Views ----------------
class RaidCheckView(discord.ui.View):
    """ปุ่มที่แปะบนข้อความเช็คชื่อในห้อง CheckRaid ให้กด 'ตอบรับ' / 'ไม่สะดวก' """
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="✅ ลุย !!", style=discord.ButtonStyle.success, custom_id="raid_accept_btn")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            channel = interaction.guild.get_channel(CHECKRAID_CHANNEL_ID)
            if not isinstance(channel, discord.TextChannel):
                return await interaction.response.send_message("❌ ไม่พบห้องเช็คชื่อ", ephemeral=True)
            msg = await channel.fetch_message(self.message_id)
            await msg.add_reaction("✅")
            await interaction.response.send_message("บันทึกการตอบรับ ✅ แล้วครับ", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ ไม่สามารถบันทึกได้: {e}", ephemeral=True)

    @discord.ui.button(label="❌ ไม่สะดวก", style=discord.ButtonStyle.danger, custom_id="raid_decline_btn")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            channel = interaction.guild.get_channel(CHECKRAID_CHANNEL_ID)
            if not isinstance(channel, discord.TextChannel):
                return await interaction.response.send_message("❌ ไม่พบห้องเช็คชื่อ", ephemeral=True)
            msg = await channel.fetch_message(self.message_id)
            await msg.add_reaction("❌")
            await interaction.response.send_message("รับทราบสถานะ ❌ แล้วครับ", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ ไม่สามารถบันทึกได้: {e}", ephemeral=True)

class RoleMessageView(discord.ui.View):
    """ปุ่ม Alarm DM หา Role"""
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Alarm", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="alarm_dm_role")
    async def alarm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_to_role(interaction, "📢 นี่คือข้อความจาก MF_BOT จ้า! ขอความร่วมมือเข้าดิสด่วนน !!")
    async def send_to_role(self, interaction: discord.Interaction, message_text: str):
        role = interaction.guild.get_role(ROLE_ID)
        if not role:
            return await interaction.response.send_message("❌ ไม่พบบทบาทนี้", ephemeral=True)
        sent = 0
        for m in role.members:
            if m.bot:
                continue
            try:
                await m.send(message_text)
                sent += 1
                await asyncio.sleep(0.4)
            except:
                pass
        await interaction.response.send_message(f"📨 ส่งข้อความให้ {sent} คนแล้ว", ephemeral=True)

class MainPanelView(discord.ui.View):
    """แผงควบคุมหลัก (โพสต์ในห้อง BOT)"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Check Raid", style=discord.ButtonStyle.primary, emoji="⚔️", custom_id="panel_start_raid_check")
    async def start_raid_check(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.channel.id != BOT_CHANNEL_ID:
            return await interaction.response.send_message("❌ ใช้ปุ่มนี้ได้เฉพาะในห้อง BOT", ephemeral=True)

        check_ch = interaction.guild.get_channel(CHECKRAID_CHANNEL_ID)
        if not isinstance(check_ch, discord.TextChannel):
            return await interaction.response.send_message("❌ ไม่พบบห้องเช็คชื่อที่ตั้งค่าไว้", ephemeral=True)

        today = datetime.datetime.now(TZ).strftime("%Y-%m-%d")
        role_mention = f"<@&{ROLE_ID}>"

        embed = discord.Embed(
            title="⚔️ เช็คชื่อ Raid/Protect 🛡️",
            description=f"วันที่ **{today}**\n{role_mention} โปรดเช็คชื่อด้วยปุ่ม/รีแอคชันด้านล่าง",
            color=0x00C853
        )
        msg = await check_ch.send(embed=embed, view=RaidCheckView(0))  # ใส่ 0 ก่อน
        await msg.edit(view=RaidCheckView(msg.id))  # ผูก message_id จริง

        try:
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
        except:
            pass

        raid_state["current"] = {
            "date": today,
            "channel_id": check_ch.id,
            "message_id": msg.id,
            "summary_sent": False
        }
        save_raid_state(raid_state)

        await interaction.response.send_message(f"✅ สร้างโพสต์เช็คชื่อแล้วใน <#{CHECKRAID_CHANNEL_ID}>", ephemeral=True)

    @discord.ui.button(label="ส่งสรุปตอนนี้", style=discord.ButtonStyle.secondary, emoji="🧾", custom_id="panel_force_summary")
    async def force_summary(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = await do_raid_summary(force=True)
        await interaction.response.send_message(res, ephemeral=True)

    @discord.ui.button(label="ส่งปุ่มลงทะเบียน", style=discord.ButtonStyle.success, emoji="📝", custom_id="panel_send_register")
    async def send_register(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.send(embed=make_register_panel_embed(), view=RegisterView())
        await interaction.response.send_message("✅ ส่งปุ่มลงทะเบียนแล้ว", ephemeral=True)

    @discord.ui.button(label=" Alarm (DM Role)", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="panel_send_alarm")
    async def send_alarm(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🚨 Alarm Sender",
            description="กดปุ่มด้านล่างเพื่อ DM แจ้งเตือนไปยัง Role เป้าหมาย",
            color=0xF44336
        )
        await interaction.channel.send(embed=embed, view=RoleMessageView())
        await interaction.response.send_message("✅ ส่งปุ่ม Alarm แล้ว", ephemeral=True)

# ---------------- สรุปเช็คชื่อ ----------------
async def do_raid_summary(force: bool = False) -> str:
    """นับรีแอคชัน ✅/❌ จากโพสต์เช็คชื่อของวันนี้ และส่งสรุปในห้องเช็คชื่อ (ครั้งเดียว/หรือ force)"""
    cur = raid_state.get("current")
    if not cur:
        return "❌ ยังไม่มีโพสต์เช็คชื่อของวันนี้"

    today = datetime.datetime.now(TZ).strftime("%Y-%m-%d")
    if cur["date"] != today and not force:
        return "❌ โพสต์เช็คชื่อที่บันทึกไว้ไม่ใช่ของวันนี้"

    if cur.get("summary_sent") and not force:
        return "ℹ️ วันนี้ส่งสรุปไปแล้ว"

    guild = bot.get_guild(GUILD_ID)
    ch = guild.get_channel(cur["channel_id"]) if guild else None
    if not isinstance(ch, discord.TextChannel):
        return "❌ ไม่พบห้องเช็คชื่อ"

    try:
        msg = await ch.fetch_message(cur["message_id"])
    except Exception as e:
        return f"❌ หาโพสต์เช็คชื่อไม่พบ: {e}"

    yes = 0
    no = 0
    for r in msg.reactions:
        try:
            if str(r.emoji) == "✅":
                yes += r.count - 1 if r.me else r.count
            if str(r.emoji) == "❌":
                no += r.count - 1 if r.me else r.count
        except:
            pass

    total = yes + no
    embed = discord.Embed(
        title=f"🧾 สรุปเช็คชื่อ • {cur['date']}",
        description=f"**ตอบรับ:** {yes} คน\n**ไม่สะดวก:** {no} คน\n**รวม:** {total} คน",
        color=0x009688
    )
    await ch.send(embed=embed)

    cur["summary_sent"] = True
    raid_state["current"] = cur
    save_raid_state(raid_state)
    return "✅ ส่งสรุปแล้ว"

@tasks.loop(minutes=1)
async def raid_summary_scheduler():
    """เช็คทุกนาที — ถ้าเวลา = 19:00 ตาม TZ และยังไม่ส่งสรุปของวันนี้ ก็ส่ง"""
    now = datetime.datetime.now(TZ)
    if now.hour == SUMMARY_HOUR and now.minute in (0, 1, 2):  # เผื่อ 3 นาทีแรก
        cur = raid_state.get("current")
        if not cur:
            return
        if cur["date"] != now.strftime("%Y-%m-%d"):
            return
        if not cur.get("summary_sent"):
            print("[SCHED] Auto summary at 19:00", flush=True)
            try:
                await do_raid_summary(force=False)
            except Exception as e:
                print(f"[SCHED] summary error: {e}", flush=True)

# ---------------- ตัวกู้โพสต์เช็คชื่อจากห้อง (เมื่อไฟล์หาย) ----------------
async def restore_raidcheck_from_channel() -> bool:
    """พยายามค้นหาโพสต์เช็คชื่อล่าสุดจากห้อง CHECKRAID แล้ว restore view"""
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("[RESTORE] Guild not found", flush=True)
        return False

    ch = guild.get_channel(CHECKRAID_CHANNEL_ID)
    if not isinstance(ch, discord.TextChannel):
        print("[RESTORE] CheckRaid channel not found", flush=True)
        return False

    try:
        async for msg in ch.history(limit=100):  # ย้อนหลังล่าสุด ~100 ข้อความ
            if msg.author.id != bot.user.id:
                continue
            if not msg.embeds:
                continue
            emb = msg.embeds[0]
            title = (emb.title or "").strip()
            if title.startswith("🌅 เช็คชื่อ") or title.startswith("⚔️ เช็คชื่อ"):
                raid_state["current"] = {
                    "date": datetime.datetime.now(TZ).strftime("%Y-%m-%d"),
                    "channel_id": ch.id,
                    "message_id": msg.id,
                    "summary_sent": False
                }
                save_raid_state(raid_state)
                bot.add_view(RaidCheckView(msg.id))
                print(f"[RESTORE] Re-attached RaidCheckView to message_id={msg.id}", flush=True)
                return True
    except Exception as e:
        print(f"[RESTORE] scan error: {e}", flush=True)
    return False

# ---------------- Commands ----------------
@bot.command(name="panel")
@commands.has_permissions(manage_guild=True)
async def cmd_panel(ctx: commands.Context):
    """ส่งแผงควบคุมไปในห้องปัจจุบัน (แนะนำใช้ในห้อง BOT)"""
    embed = discord.Embed(
        title="🛠️ MF_BOT Control Panel 🛠️",
        description=(
            "• **Check Raid**: สร้างโพสต์เช็คชื่อที่ห้องเช็คชื่อ พร้อมปุ่ม/รีแอคชัน\n"
            "• **ส่งสรุปตอนนี้**: นับผลและสรุปทันที (ไม่ต้องรอ 19:00)\n"
            "• **ส่งปุ่มลงทะเบียน**: เปิดฟอร์มลงทะเบียน (ชื่อเล่น/อายุ) — กดซ้ำเพื่ออัปเดตได้\n"
            "• **Alarm (DM Role)**: ส่งปุ่มแจ้งเตือน DM หาทุกคน"
        ),
        color=0xFFD700
    )
    embed.set_footer(text="MF_BOT • Control Panel")
    await ctx.send(embed=embed, view=MainPanelView())

@bot.command(name="ปุ่ม")
async def cmd_buttons(ctx: commands.Context):
    """ปุ่ม Alarm DM (เวอร์ชันเดี่ยว)"""
    if ctx.channel.id != BOT_CHANNEL_ID:
        await ctx.send("❌ ใช้คำสั่งนี้ได้เฉพาะในห้อง BOT เท่านั้น")
        return
    embed = discord.Embed(
        title="🚨 Alarm Sender",
        description="กดปุ่มด้านล่างเพื่อ DM แจ้งเตือนไปยัง Role เป้าหมาย",
        color=0xF44336
    )
    await ctx.send(embed=embed, view=RoleMessageView())

@bot.command(name="เช็คชื่อ")
async def cmd_checkin(ctx: commands.Context):
    """โพสต์เช็คชื่อด้วยรีแอคชัน (ทางเลือก)"""
    if ctx.channel.id != CHECKRAID_CHANNEL_ID:
        await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะในห้องเช็คชื่อที่กำหนดเท่านั้น!")
        return
    today = datetime.datetime.now(TZ).strftime("%Y-%m-%d")
    role_mention = f"<@&{ROLE_ID}>"
    embed = discord.Embed(
        title="🌅 เช็คชื่อ Raid/Protect",
        description=f"วันที่ **{today}** \n{role_mention} โปรดเช็คชื่อด้วยรีแอคชันด้านล่าง",
        color=0x00C853
    )
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    raid_state["current"] = {
        "date": today,
        "channel_id": ctx.channel.id,
        "message_id": msg.id,
        "summary_sent": False
    }
    save_raid_state(raid_state)

@bot.command(name="ลงทะเบียน")
async def cmd_register(ctx: commands.Context):
    await ctx.send(embed=make_register_panel_embed(), view=RegisterView())

@bot.command(name="myinfo")
async def cmd_myinfo(ctx: commands.Context):
    row = registered_users.get(ctx.author.id)
    emb = build_myinfo_embed(ctx.author, row)
    await ctx.reply(embed=emb, mention_author=False)

@bot.command(name="unregister")
async def cmd_unregister(ctx: commands.Context):
    if ctx.author.id in registered_users:
        registered_users.pop(ctx.author.id, None)
        _save_registered(registered_users)
        await ctx.reply("ลบข้อมูลลงทะเบียนของคุณแล้ว ✅", mention_author=False)
    else:
        await ctx.reply("ไม่พบบันทึกของคุณนะครับ", mention_author=False)

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

    # เริ่ม tasks (กันซ้ำด้วย try/except)
    try:
        update_status.start()
    except RuntimeError:
        pass
    try:
        raid_summary_scheduler.start()
    except RuntimeError:
        pass

    # ---------- Restore persistent views ----------
    bot.add_view(MainPanelView())
    bot.add_view(RoleMessageView())
    bot.add_view(RegisterView())

    # 1) พยายาม restore จากไฟล์ก่อน
    restored = False
    try:
        cur = raid_state.get("current")
        if cur and isinstance(cur.get("message_id"), int):
            bot.add_view(RaidCheckView(cur["message_id"]))
            print(f"[RESTORE] RaidCheckView restored for message_id={cur['message_id']}", flush=True)
            restored = True
    except Exception as e:
        print(f"[RESTORE] Failed to restore from file: {e}", flush=True)

    # 2) ถ้าไฟล์หาย (เช่น Render ฟรี) → ลองค้นจากห้องย้อนหลัง
    if not restored:
        ok = await restore_raidcheck_from_channel()
        if not ok:
            print("[RESTORE] No raid_check message to restore", flush=True)

@tasks.loop(seconds=STATUS_UPDATE_INTERVAL)
async def update_status():
    guild = bot.get_guild(GUILD_ID)
    if guild:
        online_members = [m for m in guild.members if m.status != discord.Status.offline and not m.bot]
        activity = discord.Game(name=f"สมาชิกออนไลน์ {len(online_members)} คน")
        await bot.change_presence(status=discord.Status.online, activity=activity)

@bot.event
async def on_disconnect():
    print("Bot disconnected! (gateway)", flush=True)

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

    except Exception as e:
        print(f"[ERROR] on_voice_state_update: {e}", flush=True)

if ENABLE_VOICE and (not FFMPEG_OK or not discord.opus.is_loaded()):
    print("[VOICE] Dependencies not ready -> disabling voice features", flush=True)
    ENABLE_VOICE = False
    
# ---------------- Main ----------------
if __name__ == "__main__":
    if HAS_KEEP_ALIVE:
        keep_alive()
    try:
        print("[BOOT] starting bot.run()", flush=True)
        bot.run(TOKEN)
        print("[BOOT] bot.run() returned (client closed).", flush=True)
    except KeyboardInterrupt:
        print("[BOOT] KeyboardInterrupt -> exiting.", flush=True)
    except Exception as e:
        print("[FATAL] bot.run crashed:", e, flush=True)
        traceback.print_exc()
        sys.exit(1)
