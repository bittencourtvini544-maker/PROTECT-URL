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
        if channel is None:
            try:
                channel = await guild.fetch_channel(int(log_channel_id))
            except Exception:
                channel = None
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

async def verificar_membro_por_id(guild_id: int, user_id: int) -> tuple[bool, str]:
    """
    Verifica se o usuario com user_id e membro do servidor usando o token do bot.
    Retorna (esta_no_servidor: bool, nome_conta: str).
    """
    nome_conta = "Desconhecido"
    try:
        guild = bot.get_guild(guild_id)
        if guild is None:
            return False, nome_conta
        try:
            member = await guild.fetch_member(user_id)
            nome_conta = member.display_name or member.name
            return True, nome_conta
        except discord.NotFound:
            return False, nome_conta
    except Exception as e:
        print(f"[SETAR] Erro ao verificar membro por ID: {e}", flush=True)
        return False, nome_conta

async def obter_id_pelo_token(token: str) -> str | None:
    """Retorna o user ID da conta do token, ou None se invalido."""
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": token}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return str(data.get("id", ""))
    except Exception:
        pass
    return None

def _discord_headers(token: str) -> dict:
    """Monta os headers padrao para requisicoes de conta de usuario."""
    return {
        "Authorization": token.strip(),
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Super-Properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6InB0LUJSIiwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzEyMC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTIwLjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjI2NjkwNSwiY2xpZW50X2V2ZW50X3NvdXJjZSI6bnVsbH0=",
        "X-Discord-Locale": "pt-BR",
    }

async def revert_vanity_with_token(guild_id: int, vanity_code: str, token: str):
    """Usa o token configurado para reverter a URL via API REST do Discord.
    Retorna (True, '') em caso de sucesso ou (False, 'mensagem de erro') em falha."""
    headers = _discord_headers(token)
    payload = {"code": vanity_code}
    # Tenta v9 e v10
    for api_version in ("v9", "v10"):
        url = f"https://discord.com/api/{api_version}/guilds/{guild_id}/vanity-url"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json=payload) as resp:
                    text = await resp.text()
                    if resp.status in (200, 204):
                        print(f"[SETAR] URL revertida ({api_version}). Status: {resp.status}", flush=True)
                        return True, ""
                    else:
                        erro = f"{api_version} HTTP {resp.status} — {text}"
                        print(f"[SETAR] Falha ({api_version}): {erro}", flush=True)
                        if api_version == "v10":
                            return False, erro
        except Exception as e:
            erro = str(e)
            print(f"[SETAR] Erro ({api_version}): {erro}", flush=True)
            if api_version == "v10":
                return False, erro
    return False, "falha desconhecida"

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
                setup_sessions[user_id]["step"] = "user_id"
                await message.channel.send(embed=discord.Embed(
                    title="Senha Correta!",
                    description=(
                        "**Passo 1 de 4 — ID da Conta**\n\n"
                        "Envie o **ID** da conta que vai fazer a reversao:\n"
                        "*(Clique com o botao direito na conta → Copiar ID)*"
                    ),
                    color=BLACK
                ))
                return

            # ── Receber ID da conta ──
            elif step == "user_id":
                id_input = message.content.strip()

                if not id_input.isdigit():
                    await message.channel.send(embed=discord.Embed(
                        title="ID invalido",
                        description="O ID precisa conter apenas numeros. Tente novamente:",
                        color=discord.Color.red()
                    ))
                    return

                conta_id_input = int(id_input)
                guild = bot.get_guild(guild_id)
                guild_name = guild.name if guild else str(guild_id)

                verificando = await message.channel.send(embed=discord.Embed(
                    title="Verificando ID...",
                    description="Aguarde, estou verificando se a conta esta no servidor.",
                    color=BLACK
                ))

                esta_no_servidor, nome_conta = await verificar_membro_por_id(guild_id, conta_id_input)
                await verificando.delete()

                if not esta_no_servidor:
                    await message.channel.send(embed=discord.Embed(
                        title="Conta nao esta no servidor",
                        description=(
                            f"O ID `{id_input}` nao foi encontrado no servidor **{guild_name}**.\n\n"
                            "A conta precisa ser membro do servidor.\n"
                            "Verifique o ID e tente novamente:"
                        ),
                        color=discord.Color.red()
                    ))
                    return

                setup_sessions[user_id]["conta_id"] = str(conta_id_input)
                setup_sessions[user_id]["nome_conta"] = nome_conta
                setup_sessions[user_id]["step"] = "token"

                await message.channel.send(embed=discord.Embed(
                    title=f"Conta encontrada: {nome_conta}",
                    description=(
                        f"ID `{id_input}` confirmado no servidor.\n\n"
                        "**Passo 2 de 4 — Token da Conta**\n\n"
                        "Envie o **token** desta conta:"
                    ),
                    color=BLACK
                ))
                return

            # ── Receber token ──
            elif step == "token":
                token_input = message.content.strip()

                verificando = await message.channel.send(embed=discord.Embed(
                    title="Verificando token...",
                    description="Aguarde, estou validando o token.",
                    color=BLACK
                ))

                # Verifica se o token e valido
                token_ok = await validar_token(token_input)
                if not token_ok:
                    await verificando.delete()
                    await message.channel.send(embed=discord.Embed(
                        title="Token Invalido",
                        description="O token fornecido e invalido. Tente novamente:",
                        color=discord.Color.red()
                    ))
                    return

                # Verifica se o token pertence ao ID informado
                token_user_id = await obter_id_pelo_token(token_input)
                await verificando.delete()

                conta_id_salvo = session.get("conta_id", "")
                if token_user_id != conta_id_salvo:
                    await message.channel.send(embed=discord.Embed(
                        title="Token nao corresponde ao ID",
                        description=(
                            "O token enviado pertence a uma conta diferente do ID informado.\n\n"
                            "Certifique-se de usar o token da conta correta e tente novamente:"
                        ),
                        color=discord.Color.red()
                    ))
                    return

                nome_conta = session.get("nome_conta", "Desconhecido")
                setup_sessions[user_id]["token"] = token_input
                setup_sessions[user_id]["step"] = "senha_conta"

                await message.channel.send(embed=discord.Embed(
                    title=f"Token confirmado: {nome_conta}",
                    description=(
                        "**Passo 3 de 4 — Senha da Conta**\n\n"
                        "Envie a **senha da conta** do Discord configurada.\n"
                        "Ela sera armazenada com seguranca.\n\n"
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
                        "**Passo 4 de 4 — Senha de Protecao do !setar**\n\n"
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
                conta_id       = setup_sessions[user_id].get("conta_id", None)

                data = load_data()
                if str(guild_id) not in data:
                    data[str(guild_id)] = {}
                data[str(guild_id)]["setar_token"]       = token_salvo
                data[str(guild_id)]["setar_senha_conta"] = encrypt_password(senha_conta)
                data[str(guild_id)]["setar_senha"]       = hash_password(senha)
                data[str(guild_id)]["setar_conta"]       = nome_conta
                data[str(guild_id)]["setar_conta_id"]    = conta_id
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

        # IDs com permissao de trocar a URL sem ban
        setar_conta_id = guild_data.get("setar_conta_id", None)
        conta_autorizada = (
            culprit and (
                culprit.id == after.owner_id or
                (setar_conta_id and str(culprit.id) == str(setar_conta_id))
            )
        )

        # Dono ou conta configurada no !setar podem trocar livremente
        if conta_autorizada:
            update_guild_data(after.id, "vanity_url", current_code)
            quem_alterou = "Dono" if culprit.id == after.owner_id else f"Conta autorizada ({guild_data.get('setar_conta', 'setar')})"
            add_log_entry(after.id, {
                "tipo": f"URL Alterada — {quem_alterou}",
                "url_anterior": protected_code,
                "url_nova": current_code,
                "por": str(culprit),
                "quando": now
            })
            log_embed = discord.Embed(
                title=f"URL Alterada — {quem_alterou}",
                color=BLACK,
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.add_field(name="URL Anterior", value=f"`discord.gg/{protected_code}`", inline=False)
            log_embed.add_field(name="Nova URL", value=f"`discord.gg/{current_code}`", inline=False)
            log_embed.add_field(name="Alterado por", value=str(culprit), inline=False)
            log_embed.set_footer(text="BOT-YOV | Alteracao autorizada")
            await send_log(after, log_embed)
            return

        revertido = False
        metodo_revert = "Nenhum"

        setar_token = guild_data.get("setar_token", None)
        nome_conta  = guild_data.get("setar_conta", "conta configurada")

        # ── Revert forcado pela conta configurada ──
        ultimo_erro_revert = ""
        if setar_token:
            # Tenta ate 5 vezes com espera crescente entre cada tentativa
            delays = [1, 2, 3, 5, 8]
            for tentativa in range(1, 6):
                revertido, ultimo_erro_revert = await revert_vanity_with_token(after.id, protected_code, setar_token)
                if revertido:
                    metodo_revert = f"Conta: {nome_conta}"
                    print(f"[SETAR] URL revertida pela conta '{nome_conta}' em {after.name} (tentativa {tentativa})", flush=True)
                    break
                else:
                    print(f"[SETAR] Tentativa {tentativa} falhou em {after.name}. Aguardando {delays[tentativa-1]}s...", flush=True)
                    await asyncio.sleep(delays[tentativa - 1])

            if not revertido:
                print(f"[SETAR] Todas as tentativas falharam em {after.name}.", flush=True)

        else:
            # Sem conta configurada: tenta com o proprio bot como unico fallback
            try:
                await after.edit(vanity_code=protected_code, reason="BOT-YOV: Revertendo troca de URL nao autorizada")
                revertido = True
                metodo_revert = "Bot"
                print(f"[BOT] URL revertida pelo bot em {after.name}", flush=True)
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[ERRO] Reverter URL (bot): {e}", flush=True)

        # ── Log de falha total ──
        if not revertido:
            if setar_token:
                aviso = (
                    f"A conta **{nome_conta}** nao conseguiu reverter a URL apos 5 tentativas.\n\n"
                    f"**Erro retornado pelo Discord:**\n```{ultimo_erro_revert or 'sem resposta'}```"
                )
            else:
                aviso = (
                    "Nenhuma conta de revert configurada e o bot nao tem permissao.\n"
                    "Use `!setar` para configurar uma conta membro do servidor."
                )
            log_embed = discord.Embed(
                title="ERRO — URL nao revertida",
                description=aviso,
                color=discord.Color.red(),
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
            title="BAN APLICADO — Troca de URL Bloqueada",
            color=BLACK,
            timestamp=datetime.now(timezone.utc)
        )
        log_embed.add_field(name="URL Protegida", value=f"`discord.gg/{protected_code}`", inline=False)
        log_embed.add_field(name="URL tentada", value=f"`discord.gg/{current_code}`" if current_code else "`desconhecida`", inline=False)
        log_embed.add_field(name="Usuario Banido", value=str(culprit) if culprit else "Nao identificado", inline=False)
        log_embed.add_field(name="URL Revertida", value=f"Sim — {metodo_revert}" if revertido else "Nao (verifique token/permissoes)", inline=False)
        log_embed.add_field(name="Quando", value=now, inline=False)
        log_embed.set_footer(text="BOT-YOV | Protecao de URL do Servidor")
        await send_log(after, log_embed)

    except Exception as e:
        print(f"[ANTI-CRASH] on_guild_update: {e}", flush=True)
        traceback.print_exc()

# ─── Commands ─────────────────────────────────────────────────────────────────

@bot.command(name="setar")
async def setar(ctx):
    """Configura uma conta de reversao de URL.
    Apenas o dono do servidor pode usar este comando."""
    try:
        # Apenas o dono geral do servidor pode configurar
        if ctx.author.id != ctx.guild.owner_id:
            try:
                await ctx.message.delete()
            except Exception:
                pass
            await ctx.send(
                embed=discord.Embed(
                    title="Sem Permissao",
                    description="Apenas o **dono do servidor** pode usar este comando.",
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
            "step": "user_id",
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
                    "Voce pode configurar qualquer conta membro do servidor para reverter "
                    "automaticamente qualquer tentativa de troca de URL."
                ),
                inline=False
            )
            painel.add_field(
                name="Requisito",
                value="A conta precisa ser **membro do servidor**.",
                inline=False
            )
            painel.add_field(
                name="Passo 1 de 4 — ID da Conta",
                value=(
                    "Envie o **ID** da conta que vai fazer a reversao:\n"
                    "*(Clique com o botao direito na conta → Copiar ID)*"
                ),
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

@bot.command(name="testar")
async def testar_token(ctx):
    """Testa se o token configurado consegue chamar a API do Discord corretamente."""
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

        guild_data = get_guild_data(ctx.guild.id)
        setar_token = guild_data.get("setar_token", None)
        nome_conta  = guild_data.get("setar_conta", None)
        protected   = guild_data.get("vanity_url", None)

        if not setar_token:
            await ctx.send(embed=discord.Embed(
                title="Nenhuma conta configurada",
                description="Use `!setar` primeiro.",
                color=BLACK
            ))
            return

        msg = await ctx.send(embed=discord.Embed(
            title="Testando token...",
            description=f"Verificando conta **{nome_conta}**...",
            color=BLACK
        ))

        # Passo 1: verificar identidade do token
        headers = _discord_headers(setar_token)
        async with aiohttp.ClientSession() as session:
            async with session.get("https://discord.com/api/v10/users/@me", headers=headers) as resp:
                texto_me = await resp.text()
                if resp.status != 200:
                    await msg.edit(embed=discord.Embed(
                        title="Token invalido",
                        description=f"A API rejeitou o token ao verificar identidade.\n```HTTP {resp.status}\n{texto_me}```",
                        color=discord.Color.red()
                    ))
                    return
                import json as _json
                dados_user = _json.loads(texto_me)
                username = dados_user.get("username", "desconhecido")

        if not protected:
            await msg.edit(embed=discord.Embed(
                title="Token valido",
                description=f"Conta identificada: **{username}**\nMas nenhuma URL protegida configurada. Use `!seturl`.",
                color=discord.Color.orange()
            ))
            return

        # Passo 2: tentar PATCH na vanity URL com a URL atual (sem mudar nada)
        revertido, erro = await revert_vanity_with_token(ctx.guild.id, protected, setar_token)

        if revertido:
            embed = discord.Embed(title="Teste bem-sucedido", color=discord.Color.green())
            embed.add_field(name="Conta", value=f"**{username}**", inline=False)
            embed.add_field(name="URL", value=f"`discord.gg/{protected}`", inline=False)
            embed.add_field(name="Resultado", value="Token valido e revert funcionando.", inline=False)
        else:
            embed = discord.Embed(title="Teste falhou — Erro ao reverter", color=discord.Color.red())
            embed.add_field(name="Conta", value=f"**{username}**", inline=False)
            embed.add_field(name="URL testada", value=f"`discord.gg/{protected}`", inline=False)
            embed.add_field(name="Erro do Discord", value=f"```{erro}```", inline=False)
            embed.set_footer(text="Token valido mas sem permissao de Gerenciar Servidor, ou URL invalida.")

        await msg.edit(embed=embed)

    except Exception as e:
        print(f"[ERRO] testar: {e}", flush=True)

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
            "`!setar` — configura conta de reversao automatica\n"
            "*(apenas o dono do servidor)*\n"
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
