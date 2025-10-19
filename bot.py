import os
import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta

# === Конфигурация ===
TOKEN = os.getenv("TOKEN")  # Токен берётся из Render Secrets
GUILD_ID = 1429442935023472714  # <-- ID твоего сервера
OWNER_ROLE_IDS = [1429445483948015727]  # <-- роли own / coown

# === Настройка интентов ===
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# === Проверка ролей ===
def is_admin():
    async def predicate(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ У вас нет прав администратора.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# === При запуске ===
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"✅ Бот запущен как {bot.user}")
    print(f"⚙️ Синхронизировано {len(tree.get_commands())} команд.")

# === BAN ===
@tree.command(name="ban", description="Забанить участника", guild=discord.Object(id=GUILD_ID))
@is_admin()
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 {member.mention} забанен. Причина: {reason}")

# === KICK ===
@tree.command(name="kick", description="Кикнуть участника", guild=discord.Object(id=GUILD_ID))
@is_admin()
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 {member.mention} кикнут. Причина: {reason}")

# === TIMEOUT ===
@tree.command(name="timeout", description="Выдать таймаут участнику", guild=discord.Object(id=GUILD_ID))
@is_admin()
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Не указана"):
    duration = timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    await interaction.response.send_message(f"⏰ {member.mention} получил таймаут на {minutes} мин. Причина: {reason}")

# === MUTE VOICE ===
@tree.command(name="mute", description="Замутить участника в войсе", guild=discord.Object(id=GUILD_ID))
@is_admin()
async def mute(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if member.voice:
        await member.edit(mute=True)
        await interaction.response.send_message(f"🔇 {member.mention} замьючен. Причина: {reason}")
    else:
        await interaction.response.send_message("❌ Этот пользователь не в голосовом канале.")

# === UNMUTE VOICE ===
@tree.command(name="unmute", description="Размутить участника", guild=discord.Object(id=GUILD_ID))
@is_admin()
async def unmute(interaction: discord.Interaction, member: discord.Member):
    if member.voice:
        await member.edit(mute=False)
        await interaction.response.send_message(f"🔊 {member.mention} размьючен.")
    else:
        await interaction.response.send_message("❌ Этот пользователь не в голосовом канале.")

# === CLEAR ===
@tree.command(name="clear", description="Удалить сообщения", guild=discord.Object(id=GUILD_ID))
@is_admin()
async def clear(interaction: discord.Interaction, amount: int):
    await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 Удалено {amount} сообщений.", ephemeral=True)

# === LOGS ===
deleted_messages = []

@bot.event
async def on_message_delete(message):
    if message.guild and not message.author.bot:
        deleted_messages.append((message.author, message.content))
        if len(deleted_messages) > 10:
            deleted_messages.pop(0)

@tree.command(name="logs", description="Показать последние удалённые сообщения", guild=discord.Object(id=GUILD_ID))
@is_admin()
async def logs(interaction: discord.Interaction):
    if not deleted_messages:
        await interaction.response.send_message("📭 Нет удалённых сообщений.")
        return

    log_text = "\n".join(
        [f"**{a.display_name}**: {c}" for a, c in deleted_messages[-10:]]
    )
    await interaction.response.send_message(f"🕵️ Последние удалённые сообщения:\n{log_text}")

# === Запуск ===
if TOKEN is None:
    raise ValueError("❌ TOKEN environment variable is not set. Добавь TOKEN в Render Secrets!")

bot.run(TOKEN)
