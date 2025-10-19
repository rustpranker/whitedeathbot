# ========================================
#  DISCORD ADMIN HELPER BOT (Replit ready)
# ========================================

import discord
from discord import app_commands, ui
from discord.ext import commands
import random, string, os, asyncio
from flask import Flask
from threading import Thread

# ----------------------------------------
# Конфигурация
# ----------------------------------------
TOKEN = "MTQyOTQ1Nzc5MTQ0NTIzNzg0MQ.GEFYMT.-E435E6L9bnl8I_6HzN7ffmy18INXB_bTAI7p4"     # токен хранится в Secrets
MASTER_KEY = "KEBAB0101"                # главный ключ
OWNER_ROLE_IDS = [1429445483948015727]  # <-- впиши ID ролей own/coown
GUILD_ID = 1429442935023472714           # <-- впиши ID твоего сервера

# ----------------------------------------
# Flask сервер для Replit (keep-alive)
# ----------------------------------------
app = Flask('')

@app.route('/')
def home():
    return "✅ Discord бот активен и работает 24/7!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ----------------------------------------
# Discord инициализация
# ----------------------------------------
INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.guilds = True
INTENTS.message_content = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

authorized_users = set()   # пользователи с доступом
valid_keys = set()         # одноразовые ключи


# ========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ========================================
def generate_key():
    letters = ''.join(random.choices(string.ascii_uppercase, k=5))
    digits = ''.join(random.choices(string.digits, k=4))
    return letters + digits

async def check_authorized(interaction: discord.Interaction):
    if interaction.user.id not in authorized_users:
        await interaction.response.send_message(
            "🚫 Вы не авторизованы. Отправьте одноразовый ключ мне в **личные сообщения**.",
            ephemeral=True
        )
        return False
    return True


# ========================================
# СОБЫТИЯ
# ========================================
@bot.event
async def on_ready():
    print(f"✅ {bot.user} запущен!")
    try:
        await bot.tree.sync()
        print("🔁 Слэш-команды синхронизированы.")
    except Exception as e:
        print("Ошибка синхронизации:", e)


@bot.event
async def on_message(message: discord.Message):
    """Авторизация через ЛС"""
    if message.author.bot:
        return

    if isinstance(message.channel, discord.DMChannel):
        text = message.content.strip().upper()

        if text == MASTER_KEY:
            authorized_users.add(message.author.id)
            await message.channel.send("✅ Главный ключ принят. Доступ к `/generate` открыт.")
            return

        if text in valid_keys:
            authorized_users.add(message.author.id)
            valid_keys.remove(text)
            await message.channel.send("🔓 Авторизация успешна! Вам доступны все команды.")
            return

        await message.channel.send("❌ Неверный или использованный ключ.")
        return

    await bot.process_commands(message)


# ========================================
# АНТИ-КРАШ УВЕДОМЛЕНИЯ
# ========================================
class DisarmButton(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ui.Button(
            label="Обезвредить",
            style=discord.ButtonStyle.primary,
            custom_id="disarm"
        ))

@bot.event
async def on_member_join(member):
    """Если на сервер заходит бот — уведомляем владельцев"""
    if member.bot:
        guild = member.guild
        for role_id in OWNER_ROLE_IDS:
            role = guild.get_role(role_id)
            if role:
                for user in role.members:
                    try:
                        view = DisarmButton()
                        await user.send(
                            "⚠️ **Подозрительная активность!**\n"
                            f"На сервер **{guild.name}** добавлен бот: {member.mention}\n\n"
                            "Возможно, сервер под атакой.\n",
                            view=view
                        )
                    except:
                        pass


# ========================================
# ГЕНЕРАЦИЯ КЛЮЧЕЙ
# ========================================
@bot.tree.command(name="generate", description="Создать одноразовый лицензионный ключ (только для владельцев MASTER ключа).")
async def generate_license(interaction: discord.Interaction):
    if interaction.user.id not in authorized_users:
        await interaction.response.send_message("🚫 Вы не авторизованы для этой команды.", ephemeral=True)
        return

    key = generate_key()
    valid_keys.add(key)
    await interaction.response.send_message(f"🪪 Новый одноразовый ключ: **{key}**", ephemeral=True)


# ========================================
# КОМАНДЫ МОДЕРАЦИИ
# ========================================

@bot.tree.command(name="kick", description="Кикнуть пользователя.")
async def kick_user(interaction: discord.Interaction, member: discord.Member, reason: str = "Без причины"):
    if not await check_authorized(interaction): return
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("❌ Нет прав на кик.", ephemeral=True)
        return
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 {member.mention} был кикнут. Причина: {reason}")

@bot.tree.command(name="ban", description="Забанить пользователя.")
async def ban_user(interaction: discord.Interaction, member: discord.Member, reason: str = "Без причины"):
    if not await check_authorized(interaction): return
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("❌ Нет прав на бан.", ephemeral=True)
        return
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 {member.mention} забанен. Причина: {reason}")

@bot.tree.command(name="clear", description="Удалить сообщения.")
async def clear_messages(interaction: discord.Interaction, amount: int = 10):
    if not await check_authorized(interaction): return
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ Нет прав на удаление.", ephemeral=True)
        return
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 Удалено {len(deleted)} сообщений.", ephemeral=True)

@bot.tree.command(name="nick", description="Изменить ник пользователю.")
async def change_nick(interaction: discord.Interaction, member: discord.Member, nickname: str):
    if not await check_authorized(interaction): return
    if not interaction.user.guild_permissions.manage_nicknames:
        await interaction.response.send_message("❌ Нет прав на смену ников.", ephemeral=True)
        return
    await member.edit(nick=nickname)
    await interaction.response.send_message(f"✏️ Ник {member.mention} изменён на **{nickname}**")

@bot.tree.command(name="mute", description="Выдать тайм-аут пользователю (в минутах).")
async def mute_user(interaction: discord.Interaction, member: discord.Member, duration: int = 10):
    if not await check_authorized(interaction): return
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("❌ Нет прав на мут.", ephemeral=True)
        return
    await member.timeout(discord.utils.utcnow() + discord.timedelta(minutes=duration))
    await interaction.response.send_message(f"🔇 {member.mention} замучен на {duration} мин.")

@bot.tree.command(name="unmute", description="Снять тайм-аут.")
async def unmute_user(interaction: discord.Interaction, member: discord.Member):
    if not await check_authorized(interaction): return
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
        return
    await member.timeout(None)
    await interaction.response.send_message(f"🔈 {member.mention} размучен.")


# ========================================
# ЗАПУСК
# ========================================
keep_alive()
bot.run(TOKEN)
