# MF_BOT_1am.py

import nextcord
from nextcord.ext import commands, tasks
from nextcord.utils import get
from dotenv import load_dotenv
from nextcord import InteractionType
import os
import asyncio
from datetime import datetime, timedelta, timezone
import aiohttp
import logging
import json
from keep_alive import keep_alive

logging.basicConfig(level=logging.INFO)              # เปลี่ยนเป็น DEBUG ได้ถ้าต้องการ
logger = logging.getLogger("mf_bot")

# โหลดตัวแปรจาก .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
VC_CHANNEL_ID = int(os.getenv("VC_CHANNEL_ID"))
TEXT_CHANNEL_ID = int(os.getenv("TEXT_CHANNEL_ID"))
STATUS_UPDATE_INTERVAL = int(os.getenv("STATUS_UPDATE_INTERVAL", 30))

intents = nextcord.Intents.all()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

joined_users = set()
RAID_DB_PATH = "raid_check.json"
last_voice_states = {}

voice_connect_lock = asyncio.Lock()
voice_client = None

ROLE_ID = 1372176652989239336  # ใส่ ID ของ Role ที่ต้องการส่งให้
BOT_CHANNEL_ID = 1403316515956064327
CheckRaid_Channel_ID = 1385971877079679006
# ====== THEME / BRAND ======
BANNER_URL = "https://i.ibb.co/3kZ0xFq/mf-logo.png"  # ใส่ภาพแบนเนอร์/โลโก้ที่อยากให้โชว์ด้านบน
ACCENT_COLOR = nextcord.Color.from_rgb(246, 189, 22)  # โทนทอง 1AM
FOOTER_ICON = "https://i.ibb.co/3kZ0xFq/mf-logo.png"
FOOTER_TEXT = "MF_BOT • ระบบลงทะเบียน"
# ============================

def _load_raid_db():
    try:
        with open(RAID_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}  # {message_id: { "date":"YYYY-MM-DD", "accept":[uid], "decline":[uid], "summary_posted": bool}}

def _save_raid_db(data: dict):
    try:
        with open(RAID_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] save raid db failed: {e}")

raid_db = _load_raid_db()

# เวลาไทย (Asia/Bangkok) = UTC+7 แบบคงที่สำหรับงานนี้
BKK = timezone(timedelta(hours=7))

def build_register_embed(ctx: nextcord.ext.commands.Context) -> nextcord.Embed:
    # ไอคอนเซิร์ฟเวอร์ (ถ้ามี)
    guild_icon = ctx.guild.icon.url if ctx.guild and ctx.guild.icon else None

    embed = nextcord.Embed(
        title="📝 ลงทะเบียนสมาชิก 1AM SCUM TEAM",
        description=(
            "คลิกปุ่ม **ลงทะเบียน** เพื่อกรอกชื่อเล่นและอายุ\n\n"
            "**เงื่อนไข**\n"
            "• ลงทะเบียนได้ **ครั้งเดียวต่อคน**\n"
            "• ชื่อจะถูกตั้งเป็นรูปแบบ `ชื่อเล่น (อายุ)`\n"
            "• หากบอทไม่สามารถเปลี่ยนชื่อได้ แสดงว่าบอทตุย\n"
        ),
        color=ACCENT_COLOR,
        timestamp=nextcord.utils.utcnow()
    )
    # แถบหัว embed
    if guild_icon:
        embed.set_author(name=ctx.guild.name, icon_url=guild_icon)

    # ภาพตัวอย่าง/แบรนด์
    # ถ้าต้องการให้โชว์ด้านล่างเต็ม กดใช้ set_image; ถ้าต้องการ thumbnail เล็ก ใช้ set_thumbnail
    embed.set_image(url=BANNER_URL)

    # บล็อกวิธีใช้งาน
    embed.add_field(
        name="วิธีใช้งาน",
        value="1) กดปุ่มด้านล่าง\n2) กรอก **ชื่อเล่น** และ **อายุ**\n3) กดส่ง แล้วรอสรุปผล",
        inline=False
    )

    # บล็อกตัวอย่างผลลัพธ์
    embed.add_field(
        name="ตัวอย่างผลลัพธ์",
        value="`ชื่อ: ม็อปแม็ปหำ49  | อายุ: 33  →  เปลี่ยนชื่อเป็น  ม็อปแม็ปหำ49 (33)`",
        inline=False
    )

    # ท้าย embed
    embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    return embed


REG_DB_PATH = "registrations.json"

def load_reg_db() -> set[int]:
    try:
        with open(REG_DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(map(int, data))
    except Exception:
        return set()

def save_reg_db(user_ids: set[int]) -> None:
    try:
        with open(REG_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(list(user_ids), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] save_reg_db failed: {e}")

registered_users: set[int] = load_reg_db()
MAX_NICK_LEN = 32

# -----------------------------
# ปุ่มส่งข้อความให้ Role
# -----------------------------
class RoleMessageView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="Alarm", style=nextcord.ButtonStyle.success)
    async def register_button(self, interaction: nextcord.Interaction, button: nextcord.ui.Button):
        await self.send_to_role(interaction, "📢 นี่คือข้อความจาก MF_BOT จ้า! ขอความร่วมมือเข้าดิสด่วนน !!")

    async def send_to_role(self, interaction: nextcord.Interaction, message_text: str):
        role = interaction.guild.get_role(ROLE_ID)
        if not role:
            await interaction.response.send_message("❌ ไม่พบบทบาทนี้", ephemeral=True)
            return

        sent_count = 0
        for member in role.members:
            try:
                await member.send(message_text)
                sent_count += 1
                await asyncio.sleep(0.5)  # กัน rate limit
            except:
                pass

        await interaction.response.send_message(f"📨 ส่งข้อความให้ {sent_count} คนแล้ว", ephemeral=True)

@bot.command()
async def ปุ่ม(ctx):
    await ctx.send("กดปุ่มด้านล่างเพื่อส่งข้อความ DM ไปขอความช่วยเหลือ", view=RoleMessageView())

@bot.command()
async def เช็คชื่อ(ctx):
    if ctx.channel.id == CheckRaid_Channel_ID:
        today = datetime.datetime.now().strftime("%d/%m/%y")
        role_mention = f"<@&{ROLE_ID}>"
        msg = await ctx.send(f"🌅 เช็คชื่อ Raid/Protect วันที่ {today} ครับ {role_mention} 💪🔥")
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
    else:
        await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะในห้องที่กำหนดเท่านั้น!")

# -----------------------------
# Event ต้อนรับสมาชิก
# -----------------------------
@bot.event
async def on_member_join(member):
    channel = bot.get_channel(1342083527067304030) #ID channel welcome
    if channel:
        embed = nextcord.Embed(
            title="🥇 ยินดีต้อนรับเข้าสู่ 1am SCUM TEAM 🥇",
            description=f"🙏 สวัสดีจ้า {member.mention}\nมานัวกับเราได้เล๊ย!",
            color=0xFFD700
        )
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
        embed.set_image(url="https://i.ibb.co/3kZ0xFq/mf-logo.png")
        embed.set_footer(text="MF_BOT • ระบบต้อนรับ", icon_url="https://i.ibb.co/3kZ0xFq/mf-logo.png")
        await channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    channel = bot.get_channel(1342083527067304030) #ID channel Goodbye
    if channel:
        embed = nextcord.Embed(
            title="😢 สมาชิกออกจากเซิร์ฟเวอร์",
            description=f"{member.name} ได้ออกจากเซิฟเวอร์แล้ว",
            color=0xFFD700
        )
        await channel.send(embed=embed)

# -----------------------------
# Voice TTS
# -----------------------------
def tts_url(text):
    return f"https://translate.google.com/translate_tts?ie=UTF-8&q={text}&tl=th&client=tw-ob"

async def play_tts(vc, text):
    url = tts_url(text)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                print(f"Failed to get TTS: {resp.status}")
                return
            with open("tts.mp3", "wb") as f:
                f.write(await resp.read())

    if not vc.is_playing():
        vc.play(nextcord.FFmpegPCMAudio("tts.mp3"))
        while vc.is_playing():
            await asyncio.sleep(1)

# -----------------------------
# Ready / Status Loop
# -----------------------------
# @bot.event
# async def on_ready():
#     bot.add_view(RegisterView())    # ถ้าข้อความเดิมยังอยู่
#     bot.add_view(RoleMessageView()) # เช่นปักหมุดไว้
#     print(f"Logged in as {bot.user} ({bot.user.id})")
#     update_status.start()

@tasks.loop(seconds=STATUS_UPDATE_INTERVAL)
async def update_status():
    guild = bot.get_guild(GUILD_ID)
    if guild:
        online_members = [m for m in guild.members if m.status != nextcord.Status.offline and not m.bot]
        activity = nextcord.Game(name=f"สมาชิกออนไลน์ {len(online_members)} คน")
        await bot.change_presence(status=nextcord.Status.online, activity=activity)

# -----------------------------
# Voice State Update
# -----------------------------

def non_bot_count(ch: nextcord.VoiceChannel) -> int:
    return sum(1 for m in ch.members if not m.bot)

@bot.event
async def on_voice_state_update(member, before, after):
    global voice_client

    if member.bot:
        return

    voice_channel = bot.get_channel(VC_CHANNEL_ID)
    if not voice_channel:
        return

    try:
        # อัปเดตตัวชี้ voice_client ปัจจุบัน
        vc_now = nextcord.utils.get(bot.voice_clients, guild=member.guild)
        if vc_now is not None:
            voice_client = vc_now

        # 1) ถ้ายังไม่มีคน (non-bot) อยู่ในห้องนี้เลย -> ถ้าบอทยังค้างอยู่ ให้ถอด
        if non_bot_count(voice_channel) == 0:
            if voice_client and voice_client.is_connected():
                # หน่วงนิดกันแกว่ง
                await asyncio.sleep(5)
                # ตรวจอีกครั้งก่อนถอด
                if non_bot_count(voice_channel) == 0:
                    await voice_client.disconnect(force=True)
                    voice_client = None
                    print("Bot ออกจากห้องเพราะไม่มีใครอยู่")
            return

        # 2) ถ้ามีคนอยู่แล้ว แต่ยังไม่ได้ต่อ -> ต่อ (โดยล็อกกัน connect ซ้อน)
        if voice_client is None or not voice_client.is_connected():
            async with voice_connect_lock:
                # ตรวจซ้ำในล็อกอีกรอบ เผื่ออีก event ต่อไปแล้ว
                vc_now = nextcord.utils.get(bot.voice_clients, guild=member.guild)
                if vc_now is None or not vc_now.is_connected():
                    print("กำลังเชื่อมต่อเข้าห้องเสียง...")
                    voice_client = await voice_channel.connect(reconnect=False)  # ปิด auto reconnect เพื่อลดซ้อน
                    print("เชื่อมต่อห้องเสียงแล้ว")

        # ====== ด้านล่าง: แจ้งเตือนเข้า/ออก/ปิดหู ฯลฯ ตามที่คุณทำ ======
        # ตัวอย่าง:
        # await play_tts(voice_client, f"{member.display_name} เข้ามาแล้วจ้า")
        # ============================================================

    except Exception as e:
        # กันล้มจากบั๊กภายใน nextcord / voice ws
        print(f"[ERROR] on_voice_state_update: {e}")

@bot.event
async def on_interaction(interaction: nextcord.Interaction):
    # log คร่าว ๆ
    try:
        if interaction.type == InteractionType.modal_submit:
            print(f"[DEBUG] on_interaction: modal_submit by {interaction.user} ({interaction.user.id})")
        # ส่งต่อให้ nextcord ประมวลผลต่อ
    finally:
        await bot.process_application_commands(interaction)

# ------- Register Modal (ปลอดภัย/ดีบักครบ) -------
class RegisterModal(nextcord.ui.Modal):
    def __init__(self):
        super().__init__(title="ลงทะเบียนสมาชิก 1am SCUM TEAM")
        self.nickname = nextcord.ui.TextInput(label="ชื่อเล่น", placeholder="ใส่ชื่อเล่นของคุณ", max_length=32)
        self.age = nextcord.ui.TextInput(label="อายุ", placeholder="ใส่อายุของคุณ", max_length=3)
        self.add_item(self.nickname)
        self.add_item(self.age)

    async def callback(self, interaction: nextcord.Interaction):
        await self._handle_submit(interaction)

    async def on_submit(self, interaction: nextcord.Interaction):
        await self._handle_submit(interaction)

    async def _handle_submit(self, interaction: nextcord.Interaction):
        user_id = interaction.user.id

        # กันซ้ำอีกชั้น เผื่อเปิด modal ทิ้งไว้
        if user_id in registered_users:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ คุณลงทะเบียนแล้ว ไม่สามารถลงทะเบียนได้อีก", ephemeral=True)
            else:
                await interaction.followup.send("❌ คุณลงทะเบียนแล้ว ไม่สามารถลงทะเบียนได้อีก", ephemeral=True)
            return

        # รับ interaction ไว้ก่อน กัน timeout
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        guild: nextcord.Guild = interaction.guild
        member: nextcord.Member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        bot_member: nextcord.Member = guild.get_member(bot.user.id) or await guild.fetch_member(bot.user.id)

        # เตรียมชื่อใหม่ (ตัดไม่ให้ยาวเกิน 32 ตัวอักษร)
        base_nick = f"{self.nickname.value.strip()} ({self.age.value.strip()})"
        new_nick = base_nick[:MAX_NICK_LEN]

        # ตรวจสิทธิ์/ลำดับ role สำคัญสำหรับการเปลี่ยนชื่อ
        reasons = []
        perms = guild.me.guild_permissions
        if not perms.manage_nicknames:
            reasons.append("บอทไม่มีสิทธิ์ **Manage Nicknames**")
        if guild.owner_id == member.id:
            reasons.append("บอทไม่สามารถเปลี่ยนชื่อ **เจ้าของเซิร์ฟเวอร์** ได้")
        if bot_member.top_role <= member.top_role:
            reasons.append("**ลำดับ Role ของบอทต้องสูงกว่า** ผู้ใช้ที่จะแก้ชื่อ")

        if reasons:
            # ยังไม่นับว่าลงทะเบียน เพื่อให้คุณไปแก้สิทธิ์/ลำดับ role แล้วลองใหม่ได้
            msg = "❌ ไม่สามารถเปลี่ยนชื่อได้ เนื่องจาก:\n- " + "\n- ".join(reasons)
            await interaction.followup.send(msg, ephemeral=True)
            return

        # เปลี่ยนชื่อ
        try:
            await member.edit(nick=new_nick, reason="Registration")
        except nextcord.Forbidden:
            await interaction.followup.send(
                "❌ เปลี่ยนชื่อไม่สำเร็จ (Forbidden)\n"
                "- เปิดสิทธิ **Manage Nicknames** ให้บอท\n"
                "- ลาก Role ของบอทให้อยู่สูงกว่า Role ของผู้ใช้",
                ephemeral=True
            )
            return
        except Exception as e:
            await interaction.followup.send(f"❌ เปลี่ยนชื่อไม่สำเร็จ: {e}", ephemeral=True)
            return

        # สำเร็จ: บันทึกว่า “ลงทะเบียนแล้ว” และรายงานผล
        registered_users.add(user_id)
        save_reg_db(registered_users)
        await interaction.followup.send(
            f"✅ ลงทะเบียนสำเร็จ\nชื่อ: **{self.nickname.value.strip()}**\nอายุ: **{self.age.value.strip()}**\n"
            f"📝 เปลี่ยนชื่อเป็น **{new_nick}** แล้ว",
            ephemeral=True

        )

# ------- ปุ่มเปิดโมดัล (persistent view + ลำดับพารามิเตอร์ถูกต้อง) -------
class RegisterView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # persistent view

    @nextcord.ui.button(
        label="ลงทะเบียน",
        style=nextcord.ButtonStyle.success,
        custom_id="btn_register_v1",
        emoji="✅"
    )
    async def register(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # ... (โค้ดเปิด Modal ของคุณ)
        await interaction.response.send_modal(RegisterModal())

# ------- on_ready: ผูก persistent view เพื่อให้ปุ่มในข้อความเก่ากดได้หลังรีสตาร์ท -------


# ------- คำสั่งส่งปุ่มใหม่ -------

@bot.command()
async def ลงทะเบียน(ctx):
    """ส่ง Embed + ปุ่มลงทะเบียนให้ทุกคนกดได้ (กันซ้ำอยู่ในปุ่ม/โมดัลแล้ว)"""
    embed = build_register_embed(ctx)  # ถ้าไม่มีฟังก์ชันนี้ ให้เปลี่ยนเป็น Embed ของคุณเอง
    await ctx.send(embed=embed, view=RegisterView())

@bot.command(name="รีเซ็ตลงทะเบียน")
@commands.has_permissions(administrator=True)
async def reset_registration(ctx, member: nextcord.Member):
    # เอา user ออกจากฐานข้อมูลกันซ้ำ + เคลียร์ nick (ถ้าต้องการ)
    try:
        if member.id in registered_users:
            registered_users.remove(member.id)
            save_reg_db(registered_users)
            # ถ้าอยากเคลียร์ชื่อเล่นเดิมออกเป็น None ให้ปลดคอมเมนต์บรรทัดล่าง
            # await member.edit(nick=None, reason="Reset registration")

            await ctx.send(f"✅ รีเซ็ตลงทะเบียนให้ {member.mention} แล้ว สามารถลงทะเบียนใหม่ได้")
        else:
            await ctx.send(f"ℹ️ {member.mention} ยังไม่เคยลงทะเบียนอยู่แล้ว")
    except Exception as e:
        await ctx.send(f"❌ รีเซ็ตไม่สำเร็จ: {e}")

@bot.command(name="เช็คลงทะเบียน")
@commands.has_permissions(administrator=True)
async def check_registration(ctx, member: nextcord.Member):
    if member.id in registered_users:
        await ctx.send(f"✅ {member.mention} ลงทะเบียนแล้ว")
    else:
        await ctx.send(f"❌ {member.mention} ยังไม่ลงทะเบียน")

class ControlPanel(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # persistent view

    @nextcord.ui.button(label="RAID_Check", style=nextcord.ButtonStyle.primary, emoji="🛡️", custom_id="btn_raid_check")
    async def btn_raid_check(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.channel.id != BOT_CHANNEL_ID:
            await interaction.response.send_message("❌ ใช้ปุ่มนี้ได้เฉพาะในห้อง BOT เท่านั้น", ephemeral=True)
            return

        check_ch = interaction.guild.get_channel(CheckRaid_Channel_ID)
        if not check_ch:
            await interaction.response.send_message("❌ ไม่พบห้องเช็คชื่อ Raid", ephemeral=True)
            return

        today = datetime.now(BKK).strftime("%d/%m/%y")
        role_mention = f"<@&{ROLE_ID}>"

        embed = nextcord.Embed(
            title="🌅 เช็คชื่อ Raid / Protect",
            description=f"วันที่ **{today}**\n{role_mention} โปรดกดปุ่มด้านล่างเพื่อแจ้งสถานะ\n"
                        f"• *** ระบบจะสรุปผลให้เวลา 19.00 น. *** •\n",
            color=nextcord.Color.from_rgb(246, 189, 22),
            timestamp=nextcord.utils.utcnow()
        )
        embed.set_footer(text="MF_BOT • RAID Check")

        # ส่งข้อความเช็คชื่อ (ชั่วคราวส่ง view ว่างก่อนเพื่อได้ message_id)
        tmp_msg = await check_ch.send(embed=embed)
        view = RaidCheckView(tmp_msg.id)
        # อัปเดตฐานข้อมูลเริ่มต้น
        raid_db[str(tmp_msg.id)] = {
            "date": datetime.now(BKK).strftime("%Y-%m-%d"),
            "accept": [],
            "decline": [],
            "summary_posted": False
        }
        _save_raid_db(raid_db)

        # แก้ข้อความให้มีปุ่ม
        await tmp_msg.edit(view=view)

        # ใส่ reaction ✅ ❌ 
        try:
            await tmp_msg.add_reaction("✅")
            await tmp_msg.add_reaction("❌")
        except Exception:
            pass

        # ตั้งเวลาสรุป 19:00 ของ "วันนี้"
        await schedule_raid_summary(interaction.guild.id, tmp_msg.channel.id, tmp_msg.id)

        await interaction.response.send_message("✅ สร้างโพสต์เช็คชื่อแล้ว และตั้งสรุปเวลา 19:00 เรียบร้อย", ephemeral=True)
    # 2) Alarm DM: ส่ง DM ถึงสมาชิกใน Role เป้าหมาย
    @nextcord.ui.button(
        label="Alarm DM",
        style=nextcord.ButtonStyle.danger,
        emoji="🚨",
        custom_id="btn_alarm_dm"
    )
    async def btn_alarm_dm(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.channel.id != BOT_CHANNEL_ID:
            await interaction.response.send_message("❌ ใช้ปุ่มนี้ได้เฉพาะในห้อง BOT เท่านั้น", ephemeral=True)
            return

        role = interaction.guild.get_role(ROLE_ID)
        if not role:
            await interaction.response.send_message("❌ ไม่พบบทบาทเป้าหมาย (ROLE_ID)", ephemeral=True)
            return

        sent = 0
        failed = 0
        text = "📢 แจ้งเตือนด่วน: โปรดเข้าร่วม RAID/Protect ตอนนี้!"
        await interaction.response.send_message("⏳ กำลังส่ง DM… (อาจใช้เวลาเล็กน้อย)", ephemeral=True)

        for m in role.members:
            try:
                await m.send(text)
                sent += 1
                await asyncio.sleep(0.3)  # กัน rate limit
            except Exception:
                failed += 1

        # ใช้ followup เพราะเรา response ไปแล้ว
        await interaction.followup.send(f"✅ ส่ง DM แล้ว {sent} คน • ❌ ส่งไม่สำเร็จ {failed} คน", ephemeral=True)

    # 3) Register: เปิด Modal ลงทะเบียน (เรียก modal ของคุณ)
    @nextcord.ui.button(
        label="ลงทะเบียน",
        style=nextcord.ButtonStyle.success,
        emoji="✅",
        custom_id="btn_open_register"
    )
    async def btn_open_register(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.channel.id != BOT_CHANNEL_ID:
            await interaction.response.send_message("❌ ใช้ปุ่มนี้ได้เฉพาะในห้อง BOT เท่านั้น", ephemeral=True)
            return

        # ถ้าคุณมีระบบกันซ้ำ/ไฟล์ registrations.json อยู่แล้ว ใช้เช็กตรงนี้ได้
        user_id = interaction.user.id
        try:
            if user_id in registered_users:
                await interaction.response.send_message("❌ คุณลงทะเบียนแล้ว ไม่สามารถลงทะเบียนได้อีก", ephemeral=True)
                return
        except NameError:
            # ถ้าไม่มีระบบ registered_users ก็ข้ามไป
            pass

        # เรียกใช้ RegisterModal ของคุณ
        try:
            await interaction.response.send_modal(RegisterModal())
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ เปิดฟอร์มไม่สำเร็จ: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ เปิดฟอร์มไม่สำเร็จ: {e}", ephemeral=True)
async def schedule_raid_summary(guild_id: int, channel_id: int, message_id: int):
    """สร้างงานสรุปยอดเวลา 19:00 ของวันที่โพสต์ (Asia/Bangkok)"""
    now = datetime.now(BKK)
    target = now.replace(hour=19, minute=0, second=0, microsecond=0)
    if now >= target:
        # ถ้ากดหลัง 19:00 ให้เลื่อนไป 19:00 ของวันถัดไป (หรือจะสรุปทันทีตามต้องการ)
        target = target + timedelta(days=1)

    delay = (target - now).total_seconds()

    async def _runner():
        try:
            await asyncio.sleep(delay)
            # ตอนถึงเวลา: โพสต์สรุป
            guild = bot.get_guild(guild_id)
            if not guild:
                return
            ch = guild.get_channel(channel_id)
            if not ch:
                return

            key = str(message_id)
            d = raid_db.get(key)
            if not d or d.get("summary_posted"):
                return

            accept_ids = list(set(d.get("accept", [])))
            decline_ids = list(set(d.get("decline", [])))
            accept_count = len(accept_ids)
            decline_count = len(decline_ids)

            # สร้างข้อความสรุป
            date_str = d.get("date", datetime.now(BKK).strftime("%Y-%m-%d"))
            def _mention_list(uids):
                # ตัดรายชื่อยาว ๆ ให้กระชับ (แสดงคนแรก ๆ + จำนวนที่เหลือ)
                if not uids:
                    return "-"
                names = []
                for uid in uids[:15]:
                    m = guild.get_member(uid)
                    names.append(m.mention if m else f"<@{uid}>")
                if len(uids) > 15:
                    names.append(f"... (+{len(uids)-15})")
                return ", ".join(names)

            embed = nextcord.Embed(
                title=f"📊 สรุปเช็คชื่อ Raid • {date_str}",
                description=(
                    f"**มาตามนัด:** {accept_count} คน\n"
                    f"{_mention_list(accept_ids)}\n\n"
                    f"**ติดธุระ/ไม่มา:** {decline_count} คน\n"
                    f"{_mention_list(decline_ids)}"
                ),
                color=nextcord.Color.green(),
                timestamp=nextcord.utils.utcnow()
            )
            embed.set_footer(text="MF_BOT • RAID Summary")

            await ch.send(embed=embed)

            # ตีธงว่าโพสต์สรุปแล้ว
            d["summary_posted"] = True
            raid_db[key] = d
            _save_raid_db(raid_db)

        except Exception as e:
            print(f"[ERR] schedule_raid_summary runner: {e}")

    asyncio.create_task(_runner())

@bot.command(name="panel")
async def panel(ctx):
    if ctx.channel.id != BOT_CHANNEL_ID:
        await ctx.send("❌ ใช้คำสั่งนี้ได้เฉพาะในห้อง BOT เท่านั้น")
        return

    embed = nextcord.Embed(
        title="🛠️ Control Panel MF_BOT 🛠️",
        description=(
            "ชุดปุ่มควบคุมสำหรับแอดมิน/สตาฟ\n"
            "• **RAID_Check**: ส่งเช็คชื่อไปห้อง Raid\n"
            "• **Alarm DM**: ส่ง DM แจ้งเตือนถึงสมาชิกทุกคน\n"
            "• **ลงทะเบียน**: เปิดแบบฟอร์มลงทะเบียนให้ผู้ใช้\n"
        ),
        color=nextcord.Color.dark_teal(),
        timestamp=nextcord.utils.utcnow()
    )
    await ctx.send(embed=embed, view=ControlPanel())

@bot.command(name="แผง")
async def panel_th(ctx):
    await panel(ctx)  # เรียกซ้ำคำสั่งเดียวกัน

class RaidCheckView(nextcord.ui.View):
    def __init__(self, message_id: int):
        # persistent view เพื่อให้กดได้หลังรีสตาร์ท
        super().__init__(timeout=None)
        self.message_id = str(message_id)

    def _ensure_entry(self):
        if self.message_id not in raid_db:
            # fallback ถ้าไม่พบ ให้ใส่โครง
            raid_db[self.message_id] = {
                "date": datetime.now(BKK).strftime("%Y-%m-%d"),
                "accept": [],
                "decline": [],
                "summary_posted": False
            }

    async def _update_embed_counts(self, interaction: nextcord.Interaction):
        """ปรับ embed เดิมให้แสดงยอดล่าสุด"""
        try:
            msg = await interaction.channel.fetch_message(int(self.message_id))
        except Exception:
            return  # หาไม่เจอ ก็ข้าม

        self._ensure_entry()
        d = raid_db[self.message_id]
        accept_count = len(set(d.get("accept", [])))
        decline_count = len(set(d.get("decline", [])))

        # ปรับ embed ตัวแรก
        if msg.embeds:
            e = msg.embeds[0]
            # อัปเดต field/description เพื่อแสดงยอด
            base_desc = e.description or ""
            # ตัดบรรทัดยอดเก่า (ถ้ามี)
            lines = [ln for ln in base_desc.splitlines() if not ln.strip().startswith(("**ยอดตอบรับ**", "**ยอดไม่มา**"))]
            lines.append(f"**ยอดตอบรับ**: {accept_count} คน")
            lines.append(f"**ยอดไม่มา**: {decline_count} คน")
            new_desc = "\n".join(lines)
            new_embed = nextcord.Embed(
                title=e.title or "เช็คชื่อ RAID/Protect",
                description=new_desc,
                color=e.color or nextcord.Color.from_rgb(246,189,22),
                timestamp=e.timestamp or nextcord.utils.utcnow()
            )
            new_embed.set_footer(text=e.footer.text if e.footer else "MF_BOT • RAID Check", icon_url=(e.footer.icon_url if (e.footer and e.footer.icon_url) else nextcord.Embed.Empty))
            new_embed.set_author(name=e.author.name if e.author else nextcord.Embed.Empty, icon_url=(e.author.icon_url if e.author else nextcord.Embed.Empty))
            new_embed.set_thumbnail(url=e.thumbnail.url if e.thumbnail else nextcord.Embed.Empty)
            new_embed.set_image(url=e.image.url if e.image else nextcord.Embed.Empty)

            try:
                await msg.edit(embed=new_embed, view=self)
            except Exception as ex:
                print(f"[WARN] cannot edit check message: {ex}")

    @nextcord.ui.button(label="พร้อมลุย (มา)", style=nextcord.ButtonStyle.success, emoji="✅", custom_id="raid_accept_btn")
    async def btn_accept(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        uid = interaction.user.id
        self._ensure_entry()
        d = raid_db[self.message_id]
        # เพิ่มใน accept และลบออกจาก decline
        s_accept = set(d.get("accept", []))
        s_decline = set(d.get("decline", []))
        s_accept.add(uid)
        if uid in s_decline:
            s_decline.remove(uid)
        d["accept"] = list(s_accept)
        d["decline"] = list(s_decline)
        _save_raid_db(raid_db)

        # ตอบแบบ ephemeral แล้วอัปเดตยอดบน embed
        if not interaction.response.is_done():
            await interaction.response.send_message("✅ บันทึกว่า 'มา' แล้ว", ephemeral=True)
        await self._update_embed_counts(interaction)

    @nextcord.ui.button(label="ติดธุระ (ไม่มา)", style=nextcord.ButtonStyle.danger, emoji="❌", custom_id="raid_decline_btn")
    async def btn_decline(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        uid = interaction.user.id
        self._ensure_entry()
        d = raid_db[self.message_id]
        s_accept = set(d.get("accept", []))
        s_decline = set(d.get("decline", []))
        s_decline.add(uid)
        if uid in s_accept:
            s_accept.remove(uid)
        d["accept"] = list(s_accept)
        d["decline"] = list(s_decline)
        _save_raid_db(raid_db)

        if not interaction.response.is_done():
            await interaction.response.send_message("✅ บันทึกว่า 'ไม่มา' แล้ว", ephemeral=True)
        await self._update_embed_counts(interaction)

@bot.event
async def on_ready():
    bot.add_view(RegisterView())
    bot.add_view(ControlPanel())
    print(f"Logged in as {bot.user} ({bot.user.id})")
    for key, d in raid_db.items():
        try:
            msg_id = int(key)
        except:
            continue
        # ผูกเฉพาะที่ยังไม่ได้โพสต์สรุป (หรือจะผูกทั้งหมดก็ได้)
        bot.add_view(RaidCheckView(msg_id))

        # ตั้งตารางสรุปใหม่ให้ด้วย ถ้ายังไม่สรุป (รองรับเคสรีสตาร์ทบอทกลางวัน)
        if not d.get("summary_posted"):
            # หา channel_id จาก CheckRaid_Channel_ID เดิม (เราใช้ห้องเดียวกัน)
            asyncio.create_task(schedule_raid_summary(
                guild_id=bot.guilds[0].id if bot.guilds else 0,
                channel_id=CheckRaid_Channel_ID,
                message_id=msg_id
            ))

if __name__ == "__main__":
    keep_alive()
    
bot.run(TOKEN)

#รันโดย python MF_BOT_1am.py