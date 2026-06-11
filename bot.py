import discord
from discord.ext import commands
import json
import os
import sys
import asyncio
import traceback
from datetime import datetime, timezone

TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "data.json"
BLACK = discord.Color(0x000000)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.moderation = True

bot = commands.Bot(command_prefix=["protec!", "!"], intents=intents, help_command=None)

# ─── Database ─────────────────────────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print("[AVISO] data.json corrompido — recriando...", flush=True)
    return {}

def save_data(data):
    try:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, DATA_FILE)
    except IOError as e:
        print(f"[ERRO] Falha ao salvar dados: {e}", flush=True)

def get_guild_data(guild_id):
    data = load_data()
    return data.get(str(guild_id), {})

def update_guild_data(guild_id, key, value):
    data = load_data()
    if str(guild_id) not in data:
        data[str(guild_id)] = {}
    data[str(guild_id)][key] = value
    save_data(data)

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

# ─── Helpers ──────────────────────────────────────────────────────────────────

async def send_log(guild, embed):
    try:
        log_channel_id = get_log_channel(guild.id)
        if not log_channel_id:
            return
        channel = guild.get_channel(int(log_channel_id))
        if channel:
            await channel.send(embed=embed)
    except Exception as e:
        print(f"[ERRO] send_log: {e}", flush=True)

async def get_who_changed(guild):
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
            return entry.user
    except Exception:
        return None

# ─── Events ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"[BOT] Online como {bot.user} (ID: {bot.user.id})", flush=True)
    print("[BOT] Protecao de URL do servidor ativada.", flush=True)
    try:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Configuracoes do servidor"
            )
        )
    except Exception:
        pass
    for guild in bot.guilds:
        try:
            data = get_guild_data(guild.id)
            if "vanity_url" not in data or not data["vanity_url"]:
                vanity = await guild.vanity_invite()
                if vanity:
                    update_guild_data(guild.id, "vanity_url", vanity.code)
                    print(f"[BOT] URL protegida salva: {vanity.code} ({guild.name})", flush=True)
        except Exception:
            pass

@bot.event
async def on_error(event, *args, **kwargs):
    """Anti-crash: captura erros em qualquer evento sem derrubar o bot."""
    print(f"[ANTI-CRASH] Erro no evento '{event}':", flush=True)
    traceback.print_exc()

@bot.event
async def on_disconnect():
    print("[BOT] Desconectado. Reconectando automaticamente...", flush=True)

@bot.event
async def on_resumed():
    print("[BOT] Reconectado com sucesso.", flush=True)

@bot.event
async def on_guild_update(before, after):
    try:
        guild_data = get_guild_data(after.id)
        protected_code = guild_data.get("vanity_url", None)

        if not protected_code:
            return

        try:
            current_invite = await after.vanity_invite()
            current_code = current_invite.code if current_invite else None
        except Exception:
            return

        if current_code == protected_code:
            return

        now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
        culprit = await get_who_changed(after)

        if culprit and culprit.id == after.owner_id:
            update_guild_data(after.id, "vanity_url", current_code)
            add_log_entry(after.id, {
                "tipo": "URL Alterada pelo Dono",
                "url_anterior": protected_code,
                "url_nova": current_code,
                "por": str(culprit),
                "quando": now
            })
            log_embed = discord.Embed(
                title="URL Alterada pelo Dono",
                color=BLACK,
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.add_field(name="URL Anterior", value=f"`discord.gg/{protected_code}`", inline=False)
            log_embed.add_field(name="Nova URL", value=f"`discord.gg/{current_code}`", inline=False)
            log_embed.add_field(name="Alterado por", value=str(culprit), inline=False)
            log_embed.set_footer(text="BOT-YOV | Alteracao permitida pelo dono")
            await send_log(after, log_embed)
            return

        try:
            await after.edit(vanity_code=protected_code, reason="BOT-YOV: Revertendo troca de URL nao autorizada")
        except discord.Forbidden:
            log_embed = discord.Embed(
                title="ERRO - Sem permissao para reverter URL",
                description="O bot precisa da permissao Gerenciar Servidor.",
                color=BLACK,
                timestamp=datetime.now(timezone.utc)
            )
            await send_log(after, log_embed)
        except Exception as e:
            print(f"[ERRO] Reverter URL: {e}", flush=True)

        if culprit:
            try:
                await after.ban(culprit, reason="BOT-YOV: Tentou trocar a URL do servidor.", delete_message_days=1)
            except Exception as e:
                print(f"[ERRO] Banir culpado: {e}", flush=True)

        add_log_entry(after.id, {
            "tipo": "Troca de URL Bloqueada + Ban",
            "url_protegida": protected_code,
            "url_tentada": current_code or "desconhecida",
            "usuario": str(culprit) if culprit else "Desconhecido",
            "usuario_id": str(culprit.id) if culprit else "N/A",
            "quando": now
        })

        log_embed = discord.Embed(
            title="BAN APLICADO - Troca de URL do Servidor",
            color=BLACK,
            timestamp=datetime.now(timezone.utc)
        )
        log_embed.add_field(name="URL Protegida", value=f"`discord.gg/{protected_code}`", inline=False)
        log_embed.add_field(name="URL que tentaram colocar", value=f"`discord.gg/{current_code}`" if current_code else "`desconhecida`", inline=False)
        log_embed.add_field(name="Usuario Banido", value=str(culprit) if culprit else "Nao identificado", inline=False)
        log_embed.add_field(name="Quando", value=now, inline=False)
        log_embed.set_footer(text="BOT-YOV | Protecao de URL do Servidor")
        await send_log(after, log_embed)

        try:
            log_channel_id = get_log_channel(after.id)
            if log_channel_id:
                channel = after.get_channel(int(log_channel_id))
                if channel:
                    embed_aviso = discord.Embed(
                        title="Tentativa de troca de URL bloqueada",
                        description=f"URL revertida para `discord.gg/{protected_code}`",
                        color=BLACK
                    )
                    if culprit:
                        embed_aviso.add_field(name="Responsavel banido", value=str(culprit), inline=False)
                    await channel.send(embed=embed_aviso)
        except Exception:
            pass

    except Exception as e:
        print(f"[ANTI-CRASH] on_guild_update: {e}", flush=True)
        traceback.print_exc()

# ─── Commands ─────────────────────────────────────────────────────────────────

@bot.command(name="seturl", aliases=["seturls"])
async def set_url(ctx):
    try:
        if ctx.author.id != ctx.guild.owner_id:
            try:
                await ctx.message.delete()
            except Exception:
                pass
            await ctx.send(
                embed=discord.Embed(title="Sem Permissao", description="Apenas o dono pode usar este comando.", color=BLACK),
                delete_after=5
            )
            return
        vanity = await ctx.guild.vanity_invite()
        if not vanity:
            await ctx.send(embed=discord.Embed(
                title="URL nao disponivel",
                description="Este servidor nao tem URL personalizada. E necessario nivel 3 de boost.",
                color=BLACK
            ))
            return
        update_guild_data(ctx.guild.id, "vanity_url", vanity.code)
        now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
        add_log_entry(ctx.guild.id, {"tipo": "URL Protegida Definida", "url": vanity.code, "por": str(ctx.author), "quando": now})
        embed = discord.Embed(title="URL do Servidor Protegida", color=BLACK)
        embed.add_field(name="URL Protegida", value=f"`discord.gg/{vanity.code}`", inline=False)
        embed.add_field(name="Definida em", value=now, inline=False)
        embed.set_footer(text="Qualquer tentativa de troca resultara em ban permanente.")
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(title="Sem Permissao", description="O bot precisa da permissao de Gerenciar Servidor.", color=BLACK))
    except Exception as e:
        print(f"[ERRO] seturl: {e}", flush=True)

@bot.command(name="url", aliases=["verurl"])
async def ver_url(ctx):
    try:
        data = get_guild_data(ctx.guild.id)
        code = data.get("vanity_url", None)
        if not code:
            await ctx.send(embed=discord.Embed(
                title="Nenhuma URL protegida",
                description="Use `!seturl` para proteger a URL atual.",
                color=BLACK
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title="URL Protegida Atual",
                description=f"`discord.gg/{code}`",
                color=BLACK
            ))
    except Exception as e:
        print(f"[ERRO] url: {e}", flush=True)

@bot.command(name="yov")
async def yov_log(ctx, action: str = None):
    try:
        if ctx.author.id != ctx.guild.owner_id:
            try:
                await ctx.message.delete()
            except Exception:
                pass
            await ctx.send(
                embed=discord.Embed(title="Sem Permissao", description="Apenas o dono pode usar este comando.", color=BLACK),
                delete_after=5
            )
            return

        if action is None or action.lower() == "criar":
            existing = discord.utils.get(ctx.guild.text_channels, name="bot-logs")
            if existing:
                update_guild_data(ctx.guild.id, "log_channel", str(existing.id))
                await ctx.send(embed=discord.Embed(
                    title="Canal de Log",
                    description=f"Canal existente usado: {existing.mention}",
                    color=BLACK
                ))
                return
            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False),
                ctx.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            channel = await ctx.guild.create_text_channel("bot-logs", overwrites=overwrites)
            update_guild_data(ctx.guild.id, "log_channel", str(channel.id))
            await ctx.send(embed=discord.Embed(
                title="Canal de Log Criado",
                description=f"Canal criado: {channel.mention}",
                color=BLACK
            ))

        elif action.lower() == "ver":
            data = get_guild_data(ctx.guild.id)
            logs = data.get("logs", [])
            if not logs:
                await ctx.send(embed=discord.Embed(title="Sem logs", description="Nenhum log registrado ainda.", color=BLACK))
                return
            desc = ""
            for log in logs[-10:][::-1]:
                desc += f"**{log.get('tipo', '?')}** — {log.get('quando', '?')}\n"
            await ctx.send(embed=discord.Embed(title="Ultimos Logs", description=desc, color=BLACK))

        elif action.lower() == "limpar":
            data = load_data()
            if str(ctx.guild.id) in data:
                data[str(ctx.guild.id)]["logs"] = []
                save_data(data)
            await ctx.send(embed=discord.Embed(title="Logs Limpos", description="Historico de logs apagado.", color=BLACK))

        else:
            await ctx.send(embed=discord.Embed(
                title="Uso correto",
                description="`!yov criar` — cria canal de log\n`!yov ver` — ve os ultimos logs\n`!yov limpar` — limpa os logs",
                color=BLACK
            ))
    except Exception as e:
        print(f"[ERRO] yov: {e}", flush=True)

@bot.command(name="restart", aliases=["reiniciar"])
async def restart(ctx):
    """Reinicia o bot. Apenas o dono do servidor pode usar."""
    try:
        if ctx.author.id != ctx.guild.owner_id:
            try:
                await ctx.message.delete()
            except Exception:
                pass
            await ctx.send(
                embed=discord.Embed(title="Sem Permissao", description="Apenas o dono do servidor pode reiniciar o bot.", color=BLACK),
                delete_after=5
            )
            return
        await ctx.send(embed=discord.Embed(
            title="Reiniciando...",
            description="O bot sera reiniciado em instantes. Aguarde alguns segundos.",
            color=BLACK
        ))
        await asyncio.sleep(1)
        os._exit(0)
    except Exception as e:
        print(f"[ERRO] restart: {e}", flush=True)

@bot.command(name="ping")
async def ping(ctx):
    try:
        latency = round(bot.latency * 1000)
        await ctx.send(embed=discord.Embed(
            title="Pong!",
            description=f"Latencia: `{latency}ms`",
            color=BLACK
        ))
    except Exception as e:
        print(f"[ERRO] ping: {e}", flush=True)

@bot.command(name="help", aliases=["ajuda", "comandos"])
async def help_cmd(ctx):
    try:
        embed = discord.Embed(title="Comandos do BOT-YOV", color=BLACK)
        embed.add_field(name="Protecao de URL", value=(
            "`!seturl` — protege a URL atual do servidor\n"
            "`!url` — mostra a URL protegida\n"
        ), inline=False)
        embed.add_field(name="Logs", value=(
            "`!yov criar` — cria canal de log\n"
            "`!yov ver` — mostra ultimos logs\n"
            "`!yov limpar` — limpa os logs\n"
        ), inline=False)
        embed.add_field(name="Geral", value=(
            "`!ping` — latencia do bot\n"
            "`!restart` — reinicia o bot (so dono)\n"
        ), inline=False)
        embed.set_footer(text="Prefixos: protec! ou !")
        await ctx.send(embed=embed)
    except Exception as e:
        print(f"[ERRO] help: {e}", flush=True)

# ─── Error Handler ────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=discord.Embed(title="Sem Permissao", description="Voce nao tem permissao para usar este comando.", color=BLACK), delete_after=5)
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send(embed=discord.Embed(title="Bot sem Permissao", description="Eu nao tenho permissoes suficientes para executar esta acao.", color=BLACK), delete_after=5)
    elif isinstance(error, (commands.MemberNotFound, commands.UserNotFound)):
        await ctx.send(embed=discord.Embed(title="Erro", description="Usuario nao encontrado.", color=BLACK), delete_after=5)
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=discord.Embed(title="Erro", description="Argumento invalido. Use `!help` para ver o uso correto.", color=BLACK), delete_after=5)
    elif isinstance(error, discord.Forbidden):
        await ctx.send(embed=discord.Embed(title="Erro", description="Nao tenho permissoes suficientes para esta acao.", color=BLACK), delete_after=5)
    else:
        print(f"[ERRO] Comando '{ctx.command}': {type(error).__name__}: {error}", flush=True)
        traceback.print_exc()

# ─── Iniciar ──────────────────────────────────────────────────────────────────

if not TOKEN:
    print("[ERRO FATAL] DISCORD_TOKEN nao definido.", flush=True)
    sys.exit(1)

try:
    bot.run(TOKEN, log_handler=None)
except discord.LoginFailure:
    print("[ERRO FATAL] Token invalido. Verifique o DISCORD_TOKEN.", flush=True)
    sys.exit(1)
except discord.PrivilegedIntentsRequired:
    print("[ERRO FATAL] Intents privilegiadas nao ativadas no Discord Developer Portal.", flush=True)
    sys.exit(1)
except KeyboardInterrupt:
    print("[BOT] Encerrado.", flush=True)
except Exception as e:
    print(f"[ERRO FATAL] {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)
