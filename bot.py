import discord
from discord.ext import commands
import re
import json
import os
from datetime import datetime, timezone

TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "data.json"

URL_REGEX = re.compile(
    r"(https?://[^\s]+|discord\.gg/[^\s]+|bit\.ly/[^\s]+|[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}(/[^\s]*)?)",
    re.IGNORECASE
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=["protec!", "!"], intents=intents, help_command=None)


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_guild_data(guild_id):
    data = load_data()
    return data.get(str(guild_id), {})


def update_guild_data(guild_id, key, value):
    data = load_data()
    if str(guild_id) not in data:
        data[str(guild_id)] = {}
    data[str(guild_id)][key] = value
    save_data(data)


def get_protected_url(guild_id):
    return get_guild_data(guild_id).get("url", None)


def get_log_channel(guild_id):
    return get_guild_data(guild_id).get("log_channel", None)


def add_log_entry(guild_id, entry):
    data = load_data()
    if str(guild_id) not in data:
        data[str(guild_id)] = {}
    if "logs" not in data[str(guild_id)]:
        data[str(guild_id)]["logs"] = []
    data[str(guild_id)]["logs"].append(entry)
    data[str(guild_id)]["logs"] = data[str(guild_id)]["logs"][-100:]
    save_data(data)


async def send_log(guild, embed):
    log_channel_id = get_log_channel(guild.id)
    if not log_channel_id:
        return
    channel = guild.get_channel(int(log_channel_id))
    if channel:
        try:
            await channel.send(embed=embed)
        except Exception:
            pass


@bot.event
async def on_ready():
    print(f"✅ Bot online como {bot.user} (ID: {bot.user.id})")
    print("🔒 Proteção de URL ativada em todos os servidores.")
    print("📋 Sistema de logs ativado. Use: protec!yov")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="🔒 Protegendo URLs 24/7"
        )
    )


@bot.command(name="yov")
async def yov_log(ctx, action: str = None):
    if ctx.author.id != ctx.guild.owner_id:
        await ctx.message.delete()
        embed = discord.Embed(
            title="❌ Sem Permissão",
            description="Apenas o **dono do servidor** pode usar este comando.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=5)
        return

    if action is None or action.lower() == "set":
        update_guild_data(ctx.guild.id, "log_channel", str(ctx.channel.id))
        now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
        add_log_entry(ctx.guild.id, {"tipo": "Canal de Log Definido", "canal": ctx.channel.name, "por": str(ctx.author), "quando": now})
        embed = discord.Embed(title="📋 Canal de Log Configurado!", description=f"Todos os eventos serão registrados em {ctx.channel.mention}", color=discord.Color.green())
        embed.add_field(name="📜 O que será registrado", value="🔨 Bans por troca de URL\n🔗 Alterações da URL protegida\n⚠️ Tentativas bloqueadas\n🗑️ Remoção de URL", inline=False)
        embed.set_footer(text="BOT-YOV | protec!yov")
        await ctx.send(embed=embed)

    elif action.lower() == "ver":
        data = get_guild_data(ctx.guild.id)
        logs = data.get("logs", [])
        if not logs:
            await ctx.send(embed=discord.Embed(title="📋 Nenhum log ainda", color=discord.Color.orange()))
            return
        embed = discord.Embed(title="📋 Últimos Logs — BOT-YOV", color=discord.Color.blue())
        for log in logs[-10:][::-1]:
            embed.add_field(name=f"🔸 {log.get('tipo', 'Evento')}", value=f"👤 `{log.get('usuario', log.get('por', 'N/A'))}`\n⏰ `{log.get('quando', 'N/A')}`", inline=False)
        embed.set_footer(text)
