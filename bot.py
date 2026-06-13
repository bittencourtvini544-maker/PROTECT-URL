import discord
from discord.ext import commands
import json
import os
import sys
import asyncio
import traceback
import hashlib
import aiohttp
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

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

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

async def validar_token(token: str) -> bool:
    """Verifica se o token e valido consultando a API do Discord."""
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": token}
            ) as resp:
                return resp.status == 200
    except Exception:
        return False

def encrypt_password(password: str) -> str:
    """Armazena a senha com hash SHA-256 (nao reversivel, apenas para verificacao)."""
    return hashlib.sha256(password.encode()).hexdigest()

async def verificar_admin_no_servidor(guild_id: int, token: str) -> tuple[bool, str]:
    """
    Verifica se a conta do token tem cargo de Administrador no servidor.
    Retorna (tem_admin: bool, nome_conta: str).
    A permissao ADMINISTRATOR vale 0x8, MANAGE_GUILD vale 0x20.
    """
    ADMINISTRATOR = 0x8
    MANAGE_GUILD  = 0x20

    headers = {"Authorization": token}
    nome_conta = "Desconhecido"

    try:
        async with aiohttp.ClientSession() as sess:
            # Busca info do membro no servidor
            async with sess.get(
                f"https://discord.com/api/v10/guilds/{guild_id}/members/@me",
                headers=headers
            ) as resp:
                if resp.status != 200:
                    return False, nome_conta
                member_data = await resp.json()

            # Nome da conta
            user = member_data.get("user", {})
            nome_conta = user.get("username", "Desconhecido")

            # Busca os cargos do servidor para calcular permissoes
            role_ids = set(member_data.get("roles", []))

            async with sess.get(
                f"https://discord.com/api/v10/guilds/{guild_id}/roles",
                headers=headers
            ) as resp:
                if resp.status != 200:
                    return False, nome_conta
                roles_data = await resp.json()

            # Verifica se algum cargo do membro tem ADMINISTRATOR ou MANAGE_GUILD
            for role in roles_data:
                if role["id"] in role_ids or role.get("name") == "@everyone":
                    perms = int(role.get("permissions", 0))
                    if perms & ADMINISTRATOR or perms & MANAGE_GUILD:
                        return True, nome_conta

            return False, nome_conta

    except Exception as e:
        print(f"[SETAR] Erro ao verificar admin: {e}", flush=True)
        return False, nome_conta

async def revert_vanity_with_token(guild_id: int, vanity_code: str, token: str) -> bool:
    """Usa o token configurado para reverter a URL via API REST do Discord."""
    url = f"https://discord.com/api/v10/guilds/{guild_id}/vanity-url"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }
    payload = {"code": vanity_code}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 204):
                    print(f"[SETAR] URL revertida com conta configurada. Status: {resp.status}", flush=True)
                    return True
                else:
                    text = await resp.text()
                    print(f"[SETAR] Falha ao reverter com conta configurada. Status: {resp.status} — {text}", flush=True)
                    return False
    except Exception as e:
        print(f"[SETAR] Erro ao usar token configurado: {e}", flush=True)
        return False

# ─── Sessoes de Setup (aguardando input por DM) ───────────────────────────────

# Estrutura: {user_id: {"step": "token"|"senha_conta"|"senha"|"verificar_senha", "guild_id": int, "token": str, "senha_conta": str, "nome_conta": str}}
setup_sessions = {}

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
    print(f"[ANTI-CRASH] Erro no evento '{event}':", flush=True)
    traceback.print_exc()

@bot.event
async def on_disconnect():
    print("[BOT] Desconectado. Reconectando automaticamente...", flush=True)

@bot.event
async def on_resumed():
    print("[BOT] Reconectado com sucesso.", flush=True)

@bot.event
async def on_message(message):
    """Captura respostas de DM para o fluxo do !setar."""
    if message.author.bot:
        await bot.process_commands(message)
        return

    if isinstance(message.channel, discord.DMChannel):
        user_id = message.author.id
        if user_id in setup_sessions:
            session = setup_sessions[user_id]
            step = session["step"]
            guild_id = session["guild_id"]

            # ── Verificar senha para reconfigurar ──
            if step == "verificar_senha":
                senha_digitada = message.content.strip()
                guild_data = get_guild_data(guild_id)
                senha_salva = guild_data.get("setar_senha", "")
                if hash_password(senha_digitada) != senha_salva:
                    await message.channel.send(embed=discord.Embed(
                        title="Senha Incorreta",
                        description="Senha errada. Operacao cancelada.",
                        color=discord.Color.red()
                    ))
                    del setup_sessions[user_id]
                    return
                setup_sessions[user_id]["step"] = "token"
                await message.channel.send(embed=discord.Embed(
                    title="Senha Correta!",
                    description="Agora envie o **novo token** da conta de reversao:",
                    color=BLACK
                ))
                return

            # ── Receber token ──
            elif step == "token":
                token_input = message.content.strip()

                verificando = discord.Embed(
                    title="Verificando token e permissoes...",
                    description="Aguarde, estou validando o token e checando se a conta tem cargo de Administrador no servidor.",
                    color=BLACK
                )
                msg_verificando = await message.channel.send(embed=verificando)

                # Passo 1: token valido?
                token_ok = await validar_token(token_input)
                if not token_ok:
                    await msg_verificando.delete()
                    await message.channel.send(embed=discord.Embed(
                        title="Token Invalido",
                        description="O token fornecido e invalido. Operacao cancelada.\nUse `!setar` novamente para tentar de novo.",
                        color=discord.Color.red()
                    ))
                    del setup_sessions[user_id]
                    return

                # Passo 2: conta tem Administrador no servidor?
                tem_admin, nome_conta = await verificar_admin_no_servidor(guild_id, token_input)
                await msg_verificando.delete()

                if not tem_admin:
                    guild = bot.get_guild(guild_id)
                    guild_name = guild.name if guild else str(guild_id)
                    await message.channel.send(embed=discord.Embed(
                        title="Sem Permissao de Administrador",
                        description=(
                            f"A conta **{nome_conta}** nao tem cargo de **Administrador** no servidor **{guild_name}**.\n\n"
                            "Para reverter a URL, a conta precisa ter o cargo de Administrador.\n"
                            "Conceda o cargo e use `!setar` novamente."
                        ),
                        color=discord.Color.red()
                    ))
                    del setup_sessions[user_id]
                    return

                # Token valido e conta tem admin — salva na sessao, pede senha da conta
                setup_sessions[user_id]["token"] = token_input
                setup_sessions[user_id]["nome_conta"] = nome_conta
                setup_sessions[user_id]["step"] = "senha_conta"

                await message.channel.send(embed=discord.Embed(
                    title=f"Conta verificada: {nome_conta}",
                    description=(
                        "A conta tem permissao de **Administrador** no servidor.\n\n"
                        "**Passo 2 de 3 — Senha da Conta**\n"
                        "Envie a **senha da conta** do Discord que foi configurada.\n"
                        "Ela sera armazenada de forma segura e usada pelo bot para realizar o revert da URL.\n\n"
                        "Envie a senha agora:"
                    ),
                    color=BLACK
                ))
                return

            # ── Receber senha da conta do Discord ──
            elif step == "senha_conta":
                senha_conta = message.content.strip()
                if len(senha_conta) < 1:
                    await message.channel.send(embed=discord.Embed(
                        title="Senha invalida",
                        description="A senha nao pode estar vazia. Tente novamente:",
                        color=discord.Color.red()
                    ))
                    return

                setup_sessions[user_id]["senha_conta"] = senha_conta
                setup_sessions[user_id]["step"] = "senha"

                await message.channel.send(embed=discord.Embed(
                    title="Senha da Conta Salva!",
                    description=(
                        "**Passo 3 de 3 — Senha de Protecao do !setar**\n\n"
                        "Agora crie uma **senha de protecao** para esta configuracao.\n"
                        "Sera exigida caso queira alterar os dados no futuro.\n\n"
                        "Envie a senha de protecao (minimo 4 caracteres):"
                    ),
                    color=BLACK
                ))
                return

            # ── Receber senha de protecao ──
            elif step == "senha":
                senha = message.content.strip()
                if len(senha) < 4:
                    await message.channel.send(embed=discord.Embed(
                        title="Senha muito curta",
                        description="A senha precisa ter pelo menos 4 caracteres. Tente novamente:",
                        color=discord.Color.red()
                    ))
                    return

                token_salvo    = setup_sessions[user_id]["token"]
                nome_conta     = setup_sessions[user_id].get("nome_conta", "Desconhecido")
                senha_conta    = setup_sessions[user_id].get("senha_conta", "")

                data = load_data()
                if str(guild_id) not in data:
                    data[str(guild_id)] = {}
                data[str(guild_id)]["setar_token"]       = token_salvo
                data[str(guild_id)]["setar_senha_conta"] = encrypt_password(senha_conta)
                data[str(guild_id)]["setar_senha"]       = hash_password(senha)
                data[str(guild_id)]["setar_conta"]       = nome_conta
                save_data(data)
                del setup_sessions[user_id]

                guild = bot.get_guild(guild_id)
                guild_name = guild.name if guild else str(guild_id)

                confirmacao = discord.Embed(
                    title="Configuracao Concluida!",
                    color=BLACK,
                    timestamp=datetime.now(timezone.utc)
                )
                confirmacao.add_field(name="Servidor", value=guild_name, inline=False)
                confirmacao.add_field(name="Conta configurada", value=nome_conta, inline=False)
                confirmacao.add_field(name="Senha da conta", value="Salva com seguranca", inline=True)
                confirmacao.add_field(name="Senha de protecao", value="Configurada", inline=True)
                confirmacao.add_field(
                    name="Como funciona",
                    value=(
                        "Quando alguem tentar alterar a URL do servidor, "
                        f"**{nome_conta}** ira reverter automaticamente usando suas credenciais e permissoes de Administrador."
                    ),
                    inline=False
                )
                confirmacao.set_footer(text="BOT-YOV | Guarde sua senha de protecao!")
                await message.channel.send(embed=confirmacao)

                if guild:
                    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
                    add_log_entry(guild_id, {
                        "tipo": "Conta de Revert Configurada",
                        "conta": nome_conta,
                        "por": str(message.author),
                        "quando": now
                    })
                    log_embed = discord.Embed(
                        title="Conta de Reversao Configurada",
                        description=f"Conta: **{nome_conta}**\nConfigurada por: {message.author.mention}",
                        color=BLACK,
                        timestamp=datetime.now(timezone.utc)
                    )
                    log_embed.set_footer(text="BOT-YOV | Configuracao de Reversao")
                    await send_log(guild, log_embed)
                return

    await bot.process_commands(message)

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

        # Dono pode trocar livremente — apenas atualiza a URL protegida
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

        revertido = False
        metodo_revert = "Nenhum"

        # ── 1. Tenta reverter com a conta configurada via !setar (prioridade) ──
        setar_token = guild_data.get("setar_token", None)
        nome_conta  = guild_data.get("setar_conta", "conta configurada")

        if setar_token:
            revertido = await revert_vanity_with_token(after.id, protected_code, setar_token)
            if revertido:
                metodo_revert = f"Conta: {nome_conta}"
                print(f"[SETAR] URL revertida pela conta '{nome_conta}' em {after.name}", flush=True)

        # ── 2. Fallback: tenta reverter com o proprio bot ──
        if not revertido:
            try:
                await after.edit(vanity_code=protected_code, reason="BOT-YOV: Revertendo troca de URL nao autorizada")
                revertido = True
                metodo_revert = "Bot (fallback)"
                print(f"[BOT] URL revertida pelo bot em {after.name}", flush=True)
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[ERRO] Reverter URL (bot): {e}", flush=True)

        # ── Log de falha total ──
        if not revertido:
            aviso = (
                "Nenhuma conta conseguiu reverter a URL.\n"
                "Verifique se a conta configurada ainda tem cargo de Administrador."
                if setar_token else
                "Nenhuma conta de revert configurada e o bot nao tem permissao.\n"
                "Use `!setar` para configurar uma conta com cargo de Administrador."
            )
            log_embed = discord.Embed(
                title="ERRO - URL nao revertida",
                description=aviso,
                color=BLACK,
                timestamp=datetime.now(timezone.utc)
            )
            await send_log(after, log_embed)

        # ── Bane o culpado ──
        if culprit:
            try:
                await after.ban(culprit, reason="BOT-YOV: Tentou trocar a URL do servidor.", delete_message_days=1)
            except Exception as e:
                print(f"[ERRO] Banir culpado: {e}", flush=True)

        add_log_entry(after.id, {
            "tipo": "Troca de URL Bloqueada + Ban",
            "url_protegida": protected_code,
            "url_tentada": current_code or "desconhecida",
            "revertido": revertido,
            "metodo": metodo_revert,
            "usuario": str(culprit) if culprit else "Desconhecido",
            "usuario_id": str(culprit.id) if culprit else "N/A",
            "quando": now
        })

        log_embed = discord.Embed(
            title="BAN APLICADO - Troca de URL Bloqueada",
            color=BLACK,
            timestamp=datetime.now(timezone.utc)
        )
        log_embed.add_field(name="URL Protegida", value=f"`discord.gg/{protected_code}`", inline=False)
        log_embed.add_field(name="URL tentada", value=f"`discord.gg/{current_code}`" if current_code else "`desconhecida`", inline=False)
        log_embed.add_field(name="Usuario Banido", value=str(culprit) if culprit else "Nao identificado", inline=False)
        log_embed.add_field(name="URL Revertida", value=f"Sim — {metodo_revert}" if revertido else "Nao (verifique permissoes)", inline=False)
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
                        description=(
                            f"URL revertida para `discord.gg/{protected_code}` por **{metodo_revert}**"
                            if revertido else
                            "Nao foi possivel reverter. Verifique permissoes."
                        ),
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

@bot.command(name="setar")
async def setar(ctx):
    """Configura uma conta de reversao de URL. Apenas administradores."""
    try:
        if not ctx.author.guild_permissions.administrator:
            try:
                await ctx.message.delete()
            except Exception:
                pass
            await ctx.send(
                embed=discord.Embed(
                    title="Sem Permissao",
                    description="Apenas administradores podem usar este comando.",
                    color=BLACK
                ),
                delete_after=5
            )
            return

        guild_data = get_guild_data(ctx.guild.id)
        tem_conta = bool(guild_data.get("setar_token"))

        if tem_conta:
            nome_conta = guild_data.get("setar_conta", "conta configurada")
            setup_sessions[ctx.author.id] = {
                "step": "verificar_senha",
                "guild_id": ctx.guild.id
            }
            try:
                await ctx.author.send(embed=discord.Embed(
                    title="Reconfigurar Conta de Reversao",
                    description=(
                        f"**Servidor:** {ctx.guild.name}\n"
                        f"**Conta atual:** {nome_conta}\n\n"
                        "Para alterar, envie a **senha de protecao** atual:"
                    ),
                    color=BLACK
                ))
                await ctx.send(
                    embed=discord.Embed(
                        title="Verifique sua DM",
                        description="Enviei uma mensagem privada para continuar a configuracao.",
                        color=BLACK
                    ),
                    delete_after=8
                )
            except discord.Forbidden:
                del setup_sessions[ctx.author.id]
                await ctx.send(
                    embed=discord.Embed(
                        title="Nao consigo enviar DM",
                        description="Abra suas DMs para este servidor e tente novamente.",
                        color=discord.Color.red()
                    ),
                    delete_after=8
                )
            return

        setup_sessions[ctx.author.id] = {
            "step": "token",
            "guild_id": ctx.guild.id
        }

        try:
            painel = discord.Embed(
                title="Configuracao de Conta de Reversao",
                color=BLACK,
                timestamp=datetime.now(timezone.utc)
            )
            painel.add_field(name="Servidor", value=ctx.guild.name, inline=False)
            painel.add_field(
                name="O que e isso?",
                value=(
                    "Voce pode configurar uma conta com cargo de **Administrador** que ira reverter "
                    "automaticamente qualquer tentativa de troca de URL."
                ),
                inline=False
            )
            painel.add_field(
                name="Requisito",
                value="A conta precisar ter o cargo de **Administrador** no servidor.",
                inline=False
            )
            painel.add_field(
                name="Passo 1 de 3 — Token",
                value="Envie o **token** da conta que deve fazer a reversao:",
                inline=False
            )
            painel.set_footer(text="BOT-YOV | Configuracao Segura via DM")
            await ctx.author.send(embed=painel)
            await ctx.send(
                embed=discord.Embed(
                    title="Verifique sua DM",
                    description="Enviei um painel de configuracao na sua mensagem privada.",
                    color=BLACK
                ),
                delete_after=8
            )
        except discord.Forbidden:
            del setup_sessions[ctx.author.id]
            await ctx.send(
                embed=discord.Embed(
                    title="Nao consigo enviar DM",
                    description="Abra suas DMs para este servidor e tente novamente.",
                    color=discord.Color.red()
                ),
                delete_after=8
            )

    except Exception as e:
        print(f"[ERRO] setar: {e}", flush=True)

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
        embed.add_field(name="Conta de Reversao", value=(
            "`!setar` — configura conta de reversao automatica (requer admin)\n"
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
