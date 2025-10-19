# bot.py — защищённый Discord модератор-бот (Render-ready)
# НЕ вставляй токен в код. Задай TOKEN в переменных окружения на Render.

import os
import json
import random
import string
import logging
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord import ui

# ---------------- config from env ----------------
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise SystemExit("ERROR: TOKEN environment variable is not set. Set TOKEN on Render.")

MASTER_KEY = os.getenv("MASTER_KEY", "KEBAB0101")
OWNER_ROLE_IDS = []
_owner_ids_env = os.getenv("OWNER_ROLE_IDS", "")
if _owner_ids_env:
    OWNER_ROLE_IDS = [int(x) for x in _owner_ids_env.split(",") if x.strip().isdigit()]

# detector params (optional to override via env)
BOT_JOIN_WINDOW_SEC = int(os.getenv("BOT_JOIN_WINDOW_SEC", "60"))
BOT_JOIN_THRESHOLD = int(os.getenv("BOT_JOIN_THRESHOLD", "2"))
CHANNEL_SIMILAR_WINDOW_SEC = int(os.getenv("CHANNEL_SIMILAR_WINDOW_SEC", "120"))
CHANNEL_SIMILAR_THRESHOLD = int(os.getenv("CHANNEL_SIMILAR_THRESHOLD", "3"))

STATE_FILE = os.getenv("STATE_FILE", "state.json")
ACTION_LOG = os.getenv("ACTION_LOG", "actions.log")
ERROR_LOG = os.getenv("ERROR_LOG", "errors.log")

# --------------- logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot_actions")
action_handler = logging.FileHandler(ACTION_LOG, encoding="utf-8")
action_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(action_handler)

err_logger = logging.getLogger("bot_errors")
err_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
err_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
err_logger.addHandler(err_handler)

def log_action(msg: str):
    logger.info(msg)

def log_error(msg: str):
    err_logger.error(msg)

# --------------- discord init ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
app_commands = bot.tree

# --------------- persistent state ----------------
state = {
    "authorized_users": [],   # пользователи с доступом
    "master_users": [],       # пользователи, введшие MASTER_KEY
    "valid_keys": [],         # одноразовые ключи
    "deleted_messages": []    # короткий лог удалённых сообщений
}

def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        log_action("State saved.")
    except Exception as e:
        log_error(f"Save state error: {e}")

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # merge into state safely
            for k in ("authorized_users", "master_users", "valid_keys", "deleted_messages"):
                if k in data:
                    state[k] = data[k]
            log_action("State loaded.")
    except Exception as e:
        log_error(f"Load state error: {e}")

load_state()

# --------------- helpers ----------------
def gen_one_time_key():
    letters = ''.join(random.choices(string.ascii_uppercase, k=5))
    digits = ''.join(random.choices(string.digits, k=4))
    return letters + digits

async def send_dm_safe(user: discord.User, content: str, view: ui.View = None):
    try:
        await user.send(content=content, view=view)
        return True
    except Exception as e:
        log_error(f"Failed DM to {getattr(user,'id',None)}: {e}")
        return False

async def get_role_members(guild: discord.Guild, role_ids: list):
    members = []
    try:
        for member in guild.members:
            for r in member.roles:
                if r.id in role_ids:
                    members.append(member)
                    break
    except Exception as e:
        log_error(f"get_role_members error: {e}")
    return members

async def is_authorized(interaction: discord.Interaction):
    uid = interaction.user.id
    if uid in state.get("authorized_users", []) or uid in state.get("master_users", []):
        return True
    await interaction.response.send_message("🚫 Вы не авторизованы. Отправьте одноразовый ключ боту в личные сообщения (DM).", ephemeral=True)
    return False

# --------------- anti-crash view (safe) ----------------
class DisarmView(ui.View):
    def __init__(self, guild_id: int, suspicious_bots: list, suspicious_channels: list):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.suspicious_bots = suspicious_bots
        self.suspicious_channels = suspicious_channels

    @ui.button(label="Обезвредить (Notify masters)", style=discord.ButtonStyle.primary)
    async def neutralize(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            if interaction.user.id not in state.get("master_users", []):
                await interaction.followup.send("Доступ запрещён — нужен мастер-ключ.", ephemeral=True)
                return
            guild = bot.get_guild(self.guild_id)
            if not guild:
                await interaction.followup.send("Сервер не найден.", ephemeral=True)
                return
            # Notify all master users via DM that neutralize was requested
            text = (f"Обезвреживание подтверждено пользователем {interaction.user} в сервере {guild.name}.\n"
                    f"Подозрительные боты: {self.suspicious_bots}\n"
                    f"Подозрительные каналы: {self.suspicious_channels}\n"
                    "Проверьте аудит-логи и примите меры вручную.")
            sent = 0
            for uid in state.get("master_users", []):
                try:
                    user = await bot.fetch_user(uid)
                    await user.send(text)
                    sent += 1
                except Exception:
                    continue
            await interaction.followup.send(f"Уведомления отправлены {sent} master-пользователям.", ephemeral=True)
            log_action(f"Neutralize confirmed by {interaction.user} in guild {self.guild_id}")
        except Exception as e:
            log_error(f"neutralize button error: {e}")
            await interaction.followup.send("Ошибка при уведомлении админов.", ephemeral=True)

# --------------- events & detectors ----------------
recent_bot_joins = []          # tuples (guild_id, bot_id, timestamp)
recent_channel_creations = []  # tuples (guild_id, channel_name, channel_id, timestamp)

@bot.event
async def on_ready():
    log_action(f"Bot ready: {bot.user} (guilds: {len(bot.guilds)})")
    try:
        await app_commands.sync()
        log_action("Slash commands synced.")
    except Exception as e:
        log_error(f"Sync error: {e}")
    cleanup_old_events.start()
    bot.loop.create_task(periodic_state_save())

@tasks.loop(seconds=30)
async def cleanup_old_events():
    now = datetime.utcnow()
    cutoff_bots = now - timedelta(seconds=BOT_JOIN_WINDOW_SEC)
    cutoff_channels = now - timedelta(seconds=CHANNEL_SIMILAR_WINDOW_SEC)
    global recent_bot_joins, recent_channel_creations
    recent_bot_joins = [t for t in recent_bot_joins if t[2] > cutoff_bots]
    recent_channel_creations = [t for t in recent_channel_creations if t[3] > cutoff_channels]

@bot.event
async def on_message_delete(message: discord.Message):
    try:
        if message.author and getattr(message.author, "bot", False):
            return
        entry = f"{datetime.utcnow().isoformat()} | G:{getattr(message.guild,'id','DM')} | {getattr(message.author,'id',None)} {getattr(message.author,'name',None)} -> {message.content}"
        state.setdefault("deleted_messages", []).append(entry)
        # keep last 500
        state["deleted_messages"] = state["deleted_messages"][-500:]
        save_state()
    except Exception as e:
        log_error(f"on_message_delete error: {e}")

@bot.event
async def on_message(message: discord.Message):
    # DM authorization
    if message.author.bot:
        return
    if isinstance(message.channel, discord.DMChannel):
        text = message.content.strip().upper()
        try:
            if text == MASTER_KEY:
                if message.author.id not in state.get("master_users", []):
                    state.setdefault("master_users", []).append(message.author.id)
                if message.author.id not in state.get("authorized_users", []):
                    state.setdefault("authorized_users", []).append(message.author.id)
                save_state()
                await message.channel.send("✅ Master-ключ принят. Вы получили полный доступ и можете генерировать одноразовые ключи (/generate).")
                log_action(f"MASTER_KEY accepted for {message.author} ({message.author.id})")
                return
            if text in state.get("valid_keys", []):
                if message.author.id not in state.get("authorized_users", []):
                    state.setdefault("authorized_users", []).append(message.author.id)
                state["valid_keys"].remove(text)
                save_state()
                await message.channel.send("🔓 Авторизация успешна — доступ предоставлен.")
                log_action(f"One-time key used by {message.author} ({message.author.id})")
                return
            await message.channel.send("❌ Неверный или использованный ключ.")
        except Exception as e:
            log_error(f"Error in DM processing: {e}")
    else:
        await bot.process_commands(message)

@bot.event
async def on_member_join(member: discord.Member):
    try:
        if not member.bot:
            return
        now = datetime.utcnow()
        recent_bot_joins.append((member.guild.id, member.id, now))
        joins = [t for t in recent_bot_joins if t[0] == member.guild.id]
        if len(joins) >= BOT_JOIN_THRESHOLD:
            await notify_owners(member.guild, f"{len(joins)} ботов присоединилось за короткое время.")
    except Exception as e:
        log_error(f"on_member_join error: {e}")

@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    try:
        now = datetime.utcnow()
        recent_channel_creations.append((channel.guild.id, channel.name, channel.id, now))
        same_named = [t for t in recent_channel_creations if t[0] == channel.guild.id and t[1].lower() == channel.name.lower()]
        if len(same_named) >= CHANNEL_SIMILAR_THRESHOLD:
            await notify_owners(channel.guild, f"{len(same_named)} канал(ов) с именем '{channel.name}' созданы за короткое время.")
    except Exception as e:
        log_error(f"on_guild_channel_create error: {e}")

async def notify_owners(guild: discord.Guild, reason: str):
    try:
        bots = [t[1] for t in recent_bot_joins if t[0] == guild.id]
        channels = [t[2] for t in recent_channel_creations if t[0] == guild.id]
        bots = list(dict.fromkeys(bots))
        channels = list(dict.fromkeys(channels))
        view = DisarmView(guild_id=guild.id, suspicious_bots=bots, suspicious_channels=channels)

        targets = []
        if OWNER_ROLE_IDS:
            targets = await get_role_members(guild, OWNER_ROLE_IDS)
        if not targets:
            owner = guild.owner
            if owner:
                targets = [owner]

        for member in targets:
            try:
                await send_dm_safe(member, f"⚠️ Мы заметили подозрительную активность на сервере **{guild.name}**.\nПричина: {reason}\nНажмите кнопку, чтобы уведомить master-пользователей.", view=view)
                log_action(f"Notify owner {member} for guild {guild.id}: {reason}")
            except Exception as e:
                log_error(f"Failed to notify owner {member.id}: {e}")
    except Exception as e:
        log_error(f"notify_owners error: {e}")

# --------------- slash commands ----------------
@app_commands.command(name="generate", description="(master) Сгенерировать одноразовый ключ")
async def slash_generate(interaction: discord.Interaction):
    try:
        if interaction.user.id not in state.get("master_users", []):
            await interaction.response.send_message("🚫 Команда доступна только master-пользователям.", ephemeral=True)
            return
        key = gen_one_time_key()
        state.setdefault("valid_keys", []).append(key)
        save_state()
        await interaction.response.send_message(f"🪪 Одноразовый ключ: `{key}`", ephemeral=True)
        log_action(f"{interaction.user} generated key {key}")
    except Exception as e:
        log_error(f"slash_generate error: {e}")
        await interaction.response.send_message("Ошибка генерации ключа.", ephemeral=True)

@app_commands.command(name="kick", description="Кикнуть пользователя")
@app_commands.describe(member="Кого кикнуть?", reason="Причина")
async def slash_kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Без причины"):
    try:
        if not await is_authorized(interaction): return
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("Нет прав на кик.", ephemeral=True)
            return
        await member.kick(reason=reason)
        await interaction.response.send_message(f"👢 {member.mention} кикнут. Причина: {reason}")
        log_action(f"{interaction.user} kicked {member} ({reason})")
    except Exception as e:
        log_error(f"slash_kick error: {e}")
        await interaction.response.send_message("Ошибка при кике.", ephemeral=True)

@app_commands.command(name="ban", description="Забанить пользователя")
@app_commands.describe(member="Кого забанить?", reason="Причина")
async def slash_ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Без причины"):
    try:
        if not await is_authorized(interaction): return
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Нет прав на бан.", ephemeral=True)
            return
        await member.ban(reason=reason)
        await interaction.response.send_message(f"🔨 {member.mention} забанен. Причина: {reason}")
        log_action(f"{interaction.user} banned {member} ({reason})")
    except Exception as e:
        log_error(f"slash_ban error: {e}")
        await interaction.response.send_message("Ошибка при бане.", ephemeral=True)

@app_commands.command(name="unban", description="Разбанить пользователя по ID")
@app_commands.describe(user_id="ID пользователя")
async def slash_unban(interaction: discord.Interaction, user_id: int):
    try:
        if not await is_authorized(interaction): return
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Нет прав на разбан.", ephemeral=True)
            return
        user = await bot.fetch_user(user_id)
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ Пользователь {user} разбанен.")
        log_action(f"{interaction.user} unbanned {user}")
    except Exception as e:
        log_error(f"slash_unban error: {e}")
        await interaction.response.send_message("Ошибка при разбане.", ephemeral=True)

@app_commands.command(name="mute", description="Дать таймаут (мут) пользователю в минутах")
@app_commands.describe(member="Кого замьютить?", minutes="Сколько минут")
async def slash_mute(interaction: discord.Interaction, member: discord.Member, minutes: int = 10):
    try:
        if not await is_authorized(interaction): return
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message("Нет прав на мут.", ephemeral=True)
            return
        until = datetime.utcnow() + timedelta(minutes=minutes)
        await member.timeout(until=until, reason=f"Muted by {interaction.user}")
        await interaction.response.send_message(f"🔇 {member.mention} замучен на {minutes} мин.")
        log_action(f"{interaction.user} muted {member} for {minutes} minutes")
    except Exception as e:
        log_error(f"slash_mute error: {e}")
        await interaction.response.send_message("Ошибка при муте.", ephemeral=True)

@app_commands.command(name="unmute", description="Снять таймаут с пользователя")
@app_commands.describe(member="Кого размутить?")
async def slash_unmute(interaction: discord.Interaction, member: discord.Member):
    try:
        if not await is_authorized(interaction): return
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message("Нет прав.", ephemeral=True)
            return
        await member.timeout(until=None, reason=f"Unmuted by {interaction.user}")
        await interaction.response.send_message(f"🔊 {member.mention} размучен.")
        log_action(f"{interaction.user} unmuted {member}")
    except Exception as e:
        log_error(f"slash_unmute error: {e}")
        await interaction.response.send_message("Ошибка при снятии мута.", ephemeral=True)

@app_commands.command(name="nick", description="Изменить ник пользователя")
@app_commands.describe(member="Кому изменить ник?", nickname="Новый ник")
async def slash_nick(interaction: discord.Interaction, member: discord.Member, nickname: str):
    try:
        if not await is_authorized(interaction): return
        if not interaction.user.guild_permissions.manage_nicknames:
            await interaction.response.send_message("Нет прав на смену ников.", ephemeral=True)
            return
        await member.edit(nick=nickname)
        await interaction.response.send_message(f"✏️ Ник {member.mention} изменён на **{nickname}**")
        log_action(f"{interaction.user} changed nick for {member} -> {nickname}")
    except Exception as e:
        log_error(f"slash_nick error: {e}")
        await interaction.response.send_message("Ошибка при смене ника.", ephemeral=True)

@app_commands.command(name="clear", description="Удалить сообщения в канале")
@app_commands.describe(amount="Сколько сообщений удалить?")
async def slash_clear(interaction: discord.Interaction, amount: int = 10):
    try:
        if not await is_authorized(interaction): return
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Нет прав на удаление сообщений.", ephemeral=True)
            return
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.response.send_message(f"🧹 Удалено {len(deleted)} сообщений.", ephemeral=True)
        log_action(f"{interaction.user} purged {len(deleted)} messages in {interaction.channel.id}")
    except Exception as e:
        log_error(f"slash_clear error: {e}")
        await interaction.response.send_message("Ошибка при удалении сообщений.", ephemeral=True)

@app_commands.command(name="purge_user", description="Удалить сообщения конкретного пользователя в этом канале (по последним N)")
@app_commands.describe(member="Пользователь", limit="Сколько последних сообщений просмотреть")
async def slash_purge_user(interaction: discord.Interaction, member: discord.Member, limit: int = 200):
    try:
        if not await is_authorized(interaction): return
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Нет прав.", ephemeral=True)
            return
        def check(m):
            return m.author.id == member.id
        deleted = await interaction.channel.purge(limit=limit, check=check)
        await interaction.response.send_message(f"🧹 Удалено {len(deleted)} сообщений пользователя {member.mention}.", ephemeral=True)
        log_action(f"{interaction.user} purged {len(deleted)} messages from {member} in {interaction.channel.id}")
    except Exception as e:
        log_error(f"slash_purge_user error: {e}")
        await interaction.response.send_message("Ошибка при purge_user.", ephemeral=True)

@app_commands.command(name="logs", description="Показать последние удалённые сообщения (в памяти)")
async def slash_logs(interaction: discord.Interaction):
    try:
        if not await is_authorized(interaction): return
        logs = state.get("deleted_messages", [])[-20:]
        if not logs:
            await interaction.response.send_message("Лог удалённых сообщений пуст.", ephemeral=True)
            return
        text = "\n".join(logs)
        if len(text) > 1900:
            text = text[-1900:]
        await interaction.response.send_message(f"```\n{text}\n```", ephemeral=True)
    except Exception as e:
        log_error(f"slash_logs error: {e}")
        await interaction.response.send_message("Ошибка при показе логов.", ephemeral=True)

# register commands
app_commands.add_command(slash_generate)
app_commands.add_command(slash_kick)
app_commands.add_command(slash_ban)
app_commands.add_command(slash_unban)
app_commands.add_command(slash_mute)
app_commands.add_command(slash_unmute)
app_commands.add_command(slash_nick)
app_commands.add_command(slash_clear)
app_commands.add_command(slash_purge_user)
app_commands.add_command(slash_logs)

# --------------- misc ----------------
@bot.event
async def on_command_error(ctx, error):
    log_error(f"Command error: {error}")
    try:
        await ctx.send("Произошла ошибка при выполнении команды.")
    except Exception:
        pass

async def periodic_state_save():
    await bot.wait_until_ready()
    while not bot.is_closed():
        save_state()
        await asyncio.sleep(30)

# --------------- run ----------------
if __name__ == "__main__":
    bot.loop.create_task(periodic_state_save())
    bot.run(TOKEN)
