import discord
from discord import app_commands
from discord.ext import commands
import os

# === Настройки ===
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # Упрощаем доступ к app_commands

# === Событие при запуске ===
@bot.event
async def on_ready():
    print(f"✅ Бот запущен как {bot.user}")
    try:
        synced = await tree.sync()
        print(f"⚙️ Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

# === Пример простой команды ===
@tree.command(name="ping", description="Проверить отклик бота")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!")

# === Пример команды /kick ===
@tree.command(name="kick", description="Кикнуть участника с сервера")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Без причины"):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("❌ У вас нет прав на кик участников.", ephemeral=True)
        return

    try:
        await member.kick(reason=reason)
        await interaction.response.send_message(f"👢 {member.mention} был кикнут. Причина: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Ошибка при кике: {e}")

# === Пример команды /ban ===
@tree.command(name="ban", description="Забанить участника на сервере")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Без причины"):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("❌ У вас нет прав на бан участников.", ephemeral=True)
        return

    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(f"🔨 {member.mention} был забанен. Причина: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Ошибка при бане: {e}")

# === Запуск ===
if __name__ == "__main__":
    TOKEN = os.getenv("TOKEN")
    if TOKEN is None:
        raise ValueError("❌ TOKEN environment variable is not set. Укажи токен на Render в Environment Variables.")
    bot.run(TOKEN)
