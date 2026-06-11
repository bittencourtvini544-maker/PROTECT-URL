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

BLACK = discord.Color(0x000000)

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
    print(f"Bot online: {bot.user} (ID: {bot.user.id})")
    print("Protecao de URL ativada.")
    print("Sistema de logs ativo. Use: protec!yov")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Protegendo URLs 24/7"
        )
    )


@bot.command(name="yov")
async def yov_log(ctx, action: str = None):
    if ctx.author.id != ctx.guild.owner_id:
        try:
            await ctx.message.delete()
        except Exception:
            pass
        embed = discord.Embed(
            title="Sem Permissao",
            description="Apenas o dono do servidor pode usar este comando.",
            color=BLACK
        )
        await ctx.send(embed=embed, delete_after=5)
        return

    if action is None or action.lower() == "criar":
        existing = discord.utils.get(ctx.guild.text_channels, name="bot-logs")
        if existing:
            update_guild_data(ctx.guild.id, "log_channel", str(existing.id))
            embed = discord.Embed(
                title="Canal de Log",
                description=f"Canal existente {existing.mention} definido como log.",
                color=BLACK
            )
            await ctx.send(embed=embed)
            return

        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(send_messages=False, read_messages=True),
            ctx.guild.me: discord.PermissionOverwrite(send_messages=True, read_messages=True)
        }
        log_channel = await ctx.guild.create_text_channel(
            name="bot-logs",
            overwrites=overwrites,
            reason="Canal de log criado pelo BOT-YOV"
        )
        update_guild_data(ctx.guild.id, "log_channel", str(log_channel.id))

        now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
        add_log_entry(ctx.guild.id, {
            "tipo": "Canal de Log Criado",
            "canal": log_channel.name,
            "por": str(ctx.author),
            "quando": now
        })

        embed = discord.Embed(
            title="Canal de Log Criado",
            description=f"Canal {log_channel.mention} criado e configurado com sucesso.",
            color=BLACK
        )
        embed.add_field(name="Canal", value=log_channel.mention, inline=True)
        embed.add_field(name="Criado em", value=now, inline=True)
        embed.add_field(
            name="O que sera registrado",
            value=(
                "Bans por troca de URL\n"
                "Definicao da URL protegida\n"
                "Tentativas bloqueadas\n"
                "Remocao de URL protegida"
            ),
            inline=False
        )
        embed.set_footer(text="BOT-YOV | protec!yov")
        await ctx.send(embed=embed)

    elif action.lower() == "set":
        update_guild_data(ctx.guild.id, "log_channel", str(ctx.channel.id))
        now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
        add_log_entry(ctx.guild.id, {
            "tipo": "Canal de Log Definido",
            "canal": ctx.channel.name,
            "por": str(ctx.author),
            "quando": now
        })
        embed = discord.Embed(
            title="Canal de Log Definido",
            description=f"Este canal {ctx.channel.mention} foi definido como canal de log.",
            color=BLACK
        )
        embed.set_footer(text="BOT-YOV | protec!yov")
        await ctx.send(embed=embed)

    elif action.lower() == "ver":
        data = get_guild_data(ctx.guild.id)
        logs = data.get("logs", [])
        if not logs:
            embed = discord.Embed(
                title="Nenhum log registrado",
                description="Os logs aparecem aqui quando eventos acontecem no servidor.",
                color=BLACK
            )
            await ctx.send(embed=embed)
            return
        embed = discord.Embed(title="Ultimos Logs - BOT-YOV", color=BLACK)
        for log in logs[-10:][::-1]:
            embed.add_field(
                name=log.get("tipo", "Evento"),
                value=(
                    f"Usuario: `{log.get('usuario', log.get('por', 'N/A'))}`\n"
                    f"Quando: `{log.get('quando', 'N/A')}`"
                ),
                inline=False
            )
        embed.set_footer(text=f"Ultimos {min(10, len(logs))} de {len(logs)} logs")
        await ctx.send(embed=embed)

    elif action.lower() == "limpar":
        data = load_data()
        if str(ctx.guild.id) in data:
            data[str(ctx.guild.id)]["logs"] = []
            save_data(data)
        await ctx.send(embed=discord.Embed(title="Logs Limpos", description="Todos os logs foram apagados.", color=BLACK))

    elif action.lower() == "remover":
        update_guild_data(ctx.guild.id, "log_channel", None)
        await ctx.send(embed=discord.Embed(title="Canal de Log Removido", description="Os logs nao serao mais enviados.", color=BLACK))

    else:
        embed = discord.Embed(title="protec!yov - Ajuda", color=BLACK)
        embed.add_field(name="protec!yov criar", value="Cria o canal de log automaticamente", inline=False)
        embed.add_field(name="protec!yov set", value="Define este canal como log", inline=False)
        embed.add_field(name="protec!yov ver", value="Mostra os ultimos 10 logs", inline=False)
        embed.add_field(name="protec!yov limpar", value="Apaga todos os logs", inline=False)
        embed.add_field(name="protec!yov remover", value="Remove o canal de log", inline=False)
        embed.set_footer(text="BOT-YOV | Apenas dono do servidor")
        await ctx.send(embed=embed)


@bot.command(name="seturls", aliases=["seturl"])
async def set_url(ctx, *, url: str = None):
    if ctx.author.id != ctx.guild.owner_id:
        try:
            await ctx.message.delete()
        except Exception:
            pass
        await ctx.send(embed=discord.Embed(title="Sem Permissao", description="Apenas o dono pode definir a URL.", color=BLACK), delete_after=5)
        return
    if not url:
        await ctx.send(embed=discord.Embed(title="Uso incorreto", description="Use: `!seturls <url>`", color=BLACK), delete_after=8)
        return
    url = url.strip()
    update_guild_data(ctx.guild.id, "url", url)
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
    add_log_entry(ctx.guild.id, {"tipo": "URL Protegida Definida", "url": url, "por": str(ctx.author), "quando": now})
    embed = discord.Embed(title="URL Protegida Definida", color=BLACK)
    embed.add_field(name="URL", value=f"`{url}`", inline=False)
    embed.set_footer(text="Qualquer outra URL enviada sera bloqueada.")
    await ctx.send(embed=embed)
    log_embed = discord.Embed(title="URL Protegida Atualizada", color=BLACK, timestamp=datetime.now(timezone.utc))
    log_embed.add_field(name="Definida por", value=str(ctx.author), inline=False)
    log_embed.add_field(name="Nova URL", value=f"`{url}`", inline=False)
    log_embed.set_footer(text="BOT-YOV | Log de Protecao")
    await send_log(ctx.guild, log_embed)


@bot.command(name="url", aliases=["verurl"])
async def ver_url(ctx):
    protected = get_protected_url(ctx.guild.id)
    if not protected:
        await ctx.send(embed=discord.Embed(title="Nenhuma URL definida", description="Use `!seturls <url>`", color=BLACK))
    else:
        await ctx.send(embed=discord.Embed(title="URL Protegida Atual", description=f"`{protected}`", color=BLACK))


@bot.command(name="removeurl")
async def remove_url(ctx):
    if ctx.author.id != ctx.guild.owner_id:
        try:
            await ctx.message.delete()
        except Exception:
            pass
        await ctx.send(embed=discord.Embed(title="Sem Permissao", color=BLACK), delete_after=5)
        return
    update_guild_data(ctx.guild.id, "url", None)
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
    add_log_entry(ctx.guild.id, {"tipo": "URL Protegida Removida", "por": str(ctx.author), "quando": now})
    await ctx.send(embed=discord.Embed(title="URL Removida", description="A protecao de URL foi desativada.", color=BLACK))
    log_embed = discord.Embed(title="Protecao de URL Desativada", color=BLACK, timestamp=datetime.now(timezone.utc))
    log_embed.add_field(name="Removida por", value=str(ctx.author), inline=False)
    log_embed.set_footer(text="BOT-YOV | Log de Protecao")
    await send_log(ctx.guild, log_embed)


@bot.event
async def on_message(message):
    if message.author.bot:
        await bot.process_commands(message)
        return
    if not message.guild:
        await bot.process_commands(message)
        return
    await bot.process_commands(message)

    protected = get_protected_url(message.guild.id)
    if not protected or message.author.id == message.guild.owner_id:
        return

    urls_found = URL_REGEX.findall(message.content)
    if not urls_found:
        return

    urls_text = [u[0] if isinstance(u, tuple) else u for u in urls_found]
    bad_urls = [u for u in urls_text if u and u.lower().strip("/") != protected.lower().strip("/")]
    if not bad_urls:
        return

    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
    channel_name = getattr(message.channel, "name", "DM")
    add_log_entry(message.guild.id, {"tipo": "URL Proibida + Ban", "usuario": str(message.author), "usuario_id": str(message.author.id), "url_enviada": ", ".join(bad_urls), "canal": channel_name, "quando": now})

    try:
        await message.delete()
    except Exception:
        pass

    try:
        await message.guild.ban(message.author, reason="Anti-Troca de URL", delete_message_days=1)
    except discord.Forbidden:
        embed_err = discord.Embed(title="Erro ao Banir", description=f"Sem permissao para banir {message.author.mention}. Coloque meu cargo acima do dele.", color=BLACK)
        try:
            await message.channel.send(embed=embed_err, delete_after=10)
        except Exception:
            pass
        log_embed = discord.Embed(title="ERRO - Sem permissao para banir", color=BLACK, timestamp=datetime.now(timezone.utc))
        log_embed.add_field(name="Usuario", value=str(message.author), inline=False)
        log_embed.add_field(name="URL enviada", value=", ".join(bad_urls), inline=False)
        await send_log(message.guild, log_embed)
        return
    except Exception:
        return

    try:
        embed_ban = discord.Embed(title="Usuario Banido Permanentemente", description=f"**{message.author}** foi banido por tentar trocar a URL.", color=BLACK)
        embed_ban.add_field(name="Usuario", value=f"{message.author} (`{message.author.id}`)", inline=False)
        embed_ban.add_field(name="URL Protegida", value=f"`{protected}`", inline=False)
        embed_ban.set_footer(text="Anti URL-Swap | BOT-YOV")
        await message.channel.send(embed=embed_ban, delete_after=15)
    except Exception:
        pass

    try:
        embed_repost = discord.Embed(title="URL Oficial do Servidor", description=protected, color=BLACK)
        embed_repost.set_footer(text="Esta e a unica URL permitida neste servidor.")
        await message.channel.send(embed=embed_repost)
    except Exception:
        pass

    log_embed = discord.Embed(title="BAN APLICADO - Troca de URL", color=BLACK, timestamp=datetime.now(timezone.utc))
    log_embed.add_field(name="Usuario Banido", value=f"{message.author} (`{message.author.id}`)", inline=False)
    log_embed.add_field(name="Canal", value=f"#{channel_name}", inline=True)
    log_embed.add_field(name="Quando", value=now, inline=True)
    log_embed.add_field(name="URL Proibida", value=f"`{', '.join(bad_urls)}`", inline=False)
    log_embed.add_field(name="URL Protegida", value=f"`{protected}`", inline=False)
    log_embed.set_footer(text="BOT-YOV | Log de Protecao")
    await send_log(message.guild, log_embed)


@bot.command(name="ajuda", aliases=["help2", "comandos"])
async def ajuda(ctx):
    embed = discord.Embed(title="Comandos BOT-YOV", description="Anti URL-Swap 24/7", color=BLACK)
    embed.add_field(name="!seturls <url>", value="Define a URL protegida (so dono)", inline=False)
    embed.add_field(name="!url", value="Mostra a URL atual", inline=False)
    embed.add_field(name="!removeurl", value="Remove a protecao (so dono)", inline=False)
    embed.add_field(name="protec!yov criar", value="Cria canal de log automaticamente (so dono)", inline=False)
    embed.add_field(name="protec!yov set", value="Define este canal como log (so dono)", inline=False)
    embed.add_field(name="protec!yov ver", value="Ultimos 10 logs", inline=False)
    embed.add_field(name="protec!yov limpar", value="Apaga os logs", inline=False)
    embed.set_footer(text="BOT-YOV | Anti URL-Swap")
    await ctx.send(embed=embed)


if __name__ == "__main__":
    if not TOKEN:
        print("ERRO: DISCORD_TOKEN nao definido!")
        exit(1)
    bot.run(TOKEN)
