import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import os
import random
from datetime import datetime


# =========================================================
# CONFIGURACIÓN
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("Falta la variable DISCORD_TOKEN")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# BASE DE DATOS
# =========================================================

DB = "hunger_games.db"

db = sqlite3.connect(DB)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios (
    guild_id INTEGER,
    user_id INTEGER,
    xp INTEGER DEFAULT 0,
    nivel INTEGER DEFAULT 1,
    mensajes INTEGER DEFAULT 0,
    victorias INTEGER DEFAULT 0,
    eliminaciones INTEGER DEFAULT 0,
    partidas INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS configuracion (
    guild_id INTEGER PRIMARY KEY,
    bienvenida INTEGER,
    despedida INTEGER,
    tickets INTEGER,
    inscripciones INTEGER,
    participantes INTEGER,
    resultados INTEGER,
    avisos_staff INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS inscripciones (
    guild_id INTEGER,
    user_id INTEGER,
    fecha TEXT,
    PRIMARY KEY (guild_id, user_id)
)
""")

db.commit()


# =========================================================
# FUNCIONES DE BASE DE DATOS
# =========================================================

def obtener_config(guild_id):

    cursor.execute(
        "SELECT * FROM configuracion WHERE guild_id = ?",
        (guild_id,)
    )

    datos = cursor.fetchone()

    if not datos:

        cursor.execute("""
        INSERT INTO configuracion (
            guild_id,
            bienvenida,
            despedida,
            tickets,
            inscripciones,
            participantes,
            resultados,
            avisos_staff
        )
        VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
        """, (guild_id,))

        db.commit()

        return obtener_config(guild_id)

    return {
        "bienvenida": datos[1],
        "despedida": datos[2],
        "tickets": datos[3],
        "inscripciones": datos[4],
        "participantes": datos[5],
        "resultados": datos[6],
        "avisos_staff": datos[7]
    }


def actualizar_config(guild_id, campo, canal_id):

    campos_validos = [
        "bienvenida",
        "despedida",
        "tickets",
        "inscripciones",
        "participantes",
        "resultados",
        "avisos_staff"
    ]

    if campo not in campos_validos:
        return

    cursor.execute(
        f"""
        UPDATE configuracion
        SET {campo} = ?
        WHERE guild_id = ?
        """,
        (canal_id, guild_id)
    )

    db.commit()


def obtener_usuario(guild_id, user_id):

    cursor.execute("""
    SELECT * FROM usuarios
    WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))

    datos = cursor.fetchone()

    if not datos:

        cursor.execute("""
        INSERT INTO usuarios (
            guild_id,
            user_id,
            xp,
            nivel,
            mensajes,
            victorias,
            eliminaciones,
            partidas
        )
        VALUES (?, ?, 0, 1, 0, 0, 0, 0)
        """, (guild_id, user_id))

        db.commit()

        return obtener_usuario(guild_id, user_id)

    return datos


def xp_necesaria(nivel):

    return nivel * 100


def participante(guild_id, user_id):

    cursor.execute("""
    SELECT 1 FROM inscripciones
    WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))

    return cursor.fetchone() is not None


def cantidad_participantes(guild_id):

    cursor.execute("""
    SELECT COUNT(*)
    FROM inscripciones
    WHERE guild_id = ?
    """, (guild_id,))

    return cursor.fetchone()[0]


def lista_participantes(guild_id):

    cursor.execute("""
    SELECT user_id
    FROM inscripciones
    WHERE guild_id = ?
    ORDER BY fecha ASC
    """, (guild_id,))

    return [fila[0] for fila in cursor.fetchall()]


# =========================================================
# ACTUALIZAR LISTA DE PARTICIPANTES
# =========================================================

async def actualizar_participantes(guild):

    config = obtener_config(guild.id)

    canal_id = config["participantes"]

    if not canal_id:
        return

    canal = guild.get_channel(canal_id)

    if not canal:
        return

    jugadores = lista_participantes(guild.id)

    texto = "## HUNGER GAMES\n\n"
    texto += f"**Participantes actuales: {len(jugadores)}**\n\n"

    if not jugadores:
        texto += "Todavía no hay participantes inscritos."
    else:

        for numero, user_id in enumerate(jugadores, start=1):

            miembro = guild.get_member(user_id)

            if miembro:
                texto += f"**{numero}.** {miembro.mention}\n"
            else:
                texto += f"**{numero}.** <@{user_id}>\n"

    texto += "\n> La lista se actualiza automáticamente."

    # Buscar mensaje anterior del bot
    mensaje_encontrado = None

    try:

        async for mensaje in canal.history(limit=50):

            if (
                mensaje.author == bot.user
                and mensaje.embeds
                and mensaje.embeds[0].title == "HUNGER GAMES"
            ):
                mensaje_encontrado = mensaje
                break

    except:
        pass

    embed = discord.Embed(
        title="HUNGER GAMES",
        description=texto,
        color=discord.Color.dark_red()
    )

    if mensaje_encontrado:

        await mensaje_encontrado.edit(embed=embed)

    else:

        await canal.send(embed=embed)


# =========================================================
# PANEL DE INSCRIPCIONES
# =========================================================

class InscribirseView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Inscribirme",
        style=discord.ButtonStyle.danger,
        custom_id="hunger_games_inscribirse"
    )
    async def inscribirse(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        guild = interaction.guild
        user = interaction.user

        if participante(guild.id, user.id):

            await interaction.response.send_message(
                "Ya estás inscrito en el Hunger Games.",
                ephemeral=True
            )

            return

        cursor.execute("""
        INSERT INTO inscripciones (
            guild_id,
            user_id,
            fecha
        )
        VALUES (?, ?, ?)
        """, (
            guild.id,
            user.id,
            datetime.now().isoformat()
        ))

        db.commit()

        await interaction.response.send_message(
            "Te has inscrito correctamente en el Hunger Games.",
            ephemeral=True
        )

        config = obtener_config(guild.id)

        # Aviso al staff
        staff_id = config["avisos_staff"]

        if staff_id:

            canal_staff = guild.get_channel(staff_id)

            if canal_staff:

                embed = discord.Embed(
                    title="Nueva inscripción",
                    description=(
                        f"{user.mention} se ha inscrito "
                        "al Hunger Games."
                    ),
                    color=discord.Color.green()
                )

                embed.add_field(
                    name="Participantes",
                    value=str(cantidad_participantes(guild.id))
                )

                await canal_staff.send(embed=embed)

        await actualizar_participantes(guild)


# =========================================================
# PANEL DE TICKETS
# =========================================================

class TicketView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Crear Ticket",
        style=discord.ButtonStyle.primary,
        custom_id="hunger_games_ticket"
    )
    async def crear_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        guild = interaction.guild
        user = interaction.user

        config = obtener_config(guild.id)

        categoria_id = config["tickets"]

        if not categoria_id:

            await interaction.response.send_message(
                "El sistema de tickets todavía no está configurado.",
                ephemeral=True
            )

            return

        categoria = guild.get_channel(categoria_id)

        if not categoria:

            await interaction.response.send_message(
                "La categoría de tickets no existe.",
                ephemeral=True
            )

            return

        nombre = f"ticket-{user.name}".lower()

        existente = discord.utils.get(
            guild.text_channels,
            name=nombre
        )

        if existente:

            await interaction.response.send_message(
                f"Ya tienes un ticket abierto: {existente.mention}",
                ephemeral=True
            )

            return

        overwrites = {

            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),

            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
        }

        canal = await guild.create_text_channel(
            nombre,
            category=categoria,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title="Ticket",
            description=(
                f"{user.mention}, explica aquí tu problema.\n\n"
                "Cuando termines, puedes cerrar el ticket."
            ),
            color=discord.Color.dark_red()
        )

        await canal.send(
            content=user.mention,
            embed=embed,
            view=CerrarTicketView()
        )

        await interaction.response.send_message(
            f"Ticket creado: {canal.mention}",
            ephemeral=True
        )


class CerrarTicketView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Cerrar Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="hunger_games_cerrar_ticket"
    )
    async def cerrar(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_message(
            "Cerrando ticket..."
        )

        await interaction.channel.delete()


# =========================================================
# BIENVENIDA
# =========================================================

@bot.event
async def on_member_join(member):

    config = obtener_config(member.guild.id)

    canal_id = config["bienvenida"]

    if not canal_id:
        return

    canal = member.guild.get_channel(canal_id)

    if not canal:
        return

    embed = discord.Embed(
        title="Bienvenido/a",
        description=(
            f"Bienvenido/a {member.mention} a "
            f"**{member.guild.name}**."
        ),
        color=discord.Color.dark_red()
    )

    await canal.send(embed=embed)


# =========================================================
# DESPEDIDA
# =========================================================

@bot.event
async def on_member_remove(member):

    config = obtener_config(member.guild.id)

    canal_id = config["despedida"]

    if not canal_id:
        return

    canal = member.guild.get_channel(canal_id)

    if not canal:
        return

    await canal.send(
        f"**{member}** ha salido del servidor."
    )


# =========================================================
# XP
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if not message.guild:
        return

    datos = obtener_usuario(
        message.guild.id,
        message.author.id
    )

    xp = datos[2]
    nivel = datos[3]
    mensajes = datos[4]

    xp += random.randint(5, 15)
    mensajes += 1

    while xp >= xp_necesaria(nivel):

        xp -= xp_necesaria(nivel)
        nivel += 1

        try:
            await message.channel.send(
                f"{message.author.mention} ha subido al nivel **{nivel}**."
            )
        except:
            pass

    cursor.execute("""
    UPDATE usuarios
    SET xp = ?, nivel = ?, mensajes = ?
    WHERE guild_id = ? AND user_id = ?
    """, (
        xp,
        nivel,
        mensajes,
        message.guild.id,
        message.author.id
    ))

    db.commit()

    await bot.process_commands(message)


# =========================================================
# CONFIGURAR CANALES
# =========================================================

@bot.tree.command(
    name="config",
    description="Configura los canales del bot"
)
@app_commands.describe(
    tipo="Tipo de canal",
    canal="Canal que utilizará el bot"
)
@app_commands.choices(tipo=[
    app_commands.Choice(
        name="Bienvenida",
        value="bienvenida"
    ),
    app_commands.Choice(
        name="Despedida",
        value="despedida"
    ),
    app_commands.Choice(
        name="Tickets",
        value="tickets"
    ),
    app_commands.Choice(
        name="Inscripciones",
        value="inscripciones"
    ),
    app_commands.Choice(
        name="Participantes",
        value="participantes"
    ),
    app_commands.Choice(
        name="Resultados",
        value="resultados"
    ),
    app_commands.Choice(
        name="Avisos Staff",
        value="avisos_staff"
    )
])
@app_commands.checks.has_permissions(administrator=True)
async def config(
    interaction: discord.Interaction,
    tipo: app_commands.Choice[str],
    canal: discord.TextChannel
):

    actualizar_config(
        interaction.guild.id,
        tipo.value,
        canal.id
    )

    await interaction.response.send_message(
        f"Canal configurado correctamente.\n\n"
        f"**{tipo.name}:** {canal.mention}",
        ephemeral=True
    )


# =========================================================
# CREAR PANEL DE INSCRIPCIONES
# =========================================================

@bot.tree.command(
    name="inscripciones",
    description="Envía el panel para inscribirse"
)
@app_commands.checks.has_permissions(administrator=True)
async def inscripciones(interaction):

    config = obtener_config(interaction.guild.id)

    canal_id = config["inscripciones"]

    if not canal_id:

        await interaction.response.send_message(
            "Primero configura el canal de inscripciones con `/config`.",
            ephemeral=True
        )

        return

    canal = interaction.guild.get_channel(canal_id)

    embed = discord.Embed(
        title="HUNGER GAMES",
        description=(
            "¿Quieres participar en el evento?\n\n"
            "Pulsa el botón **Inscribirme** para registrarte."
        ),
        color=discord.Color.dark_red()
    )

    embed.set_footer(
        text="Las inscripciones quedan registradas automáticamente."
    )

    await canal.send(
        embed=embed,
        view=InscribirseView()
    )

    await interaction.response.send_message(
        "Panel de inscripciones enviado.",
        ephemeral=True
    )


# =========================================================
# CREAR PANEL DE TICKETS
# =========================================================

@bot.tree.command(
    name="tickets",
    description="Envía el panel de tickets"
)
@app_commands.checks.has_permissions(administrator=True)
async def tickets(interaction):

    config = obtener_config(interaction.guild.id)

    if not config["tickets"]:

        await interaction.response.send_message(
            "Primero configura la categoría de tickets.",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="SOPORTE",
        description=(
            "Si necesitas ayuda, pulsa el botón "
            "para crear un ticket."
        ),
        color=discord.Color.dark_red()
    )

    await interaction.channel.send(
        embed=embed,
        view=TicketView()
    )

    await interaction.response.send_message(
        "Panel de tickets enviado.",
        ephemeral=True
    )


# =========================================================
# STATS
# =========================================================

@bot.tree.command(
    name="stats",
    description="Muestra tus estadísticas"
)
async def stats(interaction):

    datos = obtener_usuario(
        interaction.guild.id,
        interaction.user.id
    )

    embed = discord.Embed(
        title=f"Estadísticas de {interaction.user}",
        color=discord.Color.dark_red()
    )

    embed.add_field(
        name="Nivel",
        value=str(datos[3]),
        inline=True
    )

    embed.add_field(
        name="XP",
        value=str(datos[2]),
        inline=True
    )

    embed.add_field(
        name="Mensajes",
        value=str(datos[4]),
        inline=True
    )

    embed.add_field(
        name="Victorias",
        value=str(datos[5]),
        inline=True
    )

    embed.add_field(
        name="Eliminaciones",
        value=str(datos[6]),
        inline=True
    )

    embed.add_field(
        name="Partidas",
        value=str(datos[7]),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# NIVEL
# =========================================================

@bot.tree.command(
    name="nivel",
    description="Muestra tu nivel"
)
async def nivel(interaction):

    datos = obtener_usuario(
        interaction.guild.id,
        interaction.user.id
    )

    await interaction.response.send_message(
        f"Tu nivel es **{datos[3]}**.\n"
        f"XP: **{datos[2]} / {xp_necesaria(datos[3])}**"
    )


# =========================================================
# PARTICIPANTES
# =========================================================

@bot.tree.command(
    name="participantes",
    description="Muestra los participantes actuales"
)
async def participantes(interaction):

    jugadores = lista_participantes(
        interaction.guild.id
    )

    texto = f"**Participantes: {len(jugadores)}**\n\n"

    if not jugadores:

        texto += "No hay participantes."

    else:

        for numero, user_id in enumerate(jugadores, 1):

            miembro = interaction.guild.get_member(user_id)

            if miembro:
                texto += f"**{numero}.** {miembro.mention}\n"
            else:
                texto += f"**{numero}.** <@{user_id}>\n"

    await interaction.response.send_message(
        texto
    )


# =========================================================
# RESULTADOS
# =========================================================

@bot.tree.command(
    name="resultado",
    description="Registra el resultado de una partida"
)
@app_commands.describe(
    jugador="Jugador",
    resultado="Resultado",
    eliminaciones="Eliminaciones realizadas"
)
@app_commands.choices(resultado=[
    app_commands.Choice(
        name="Victoria",
        value="victoria"
    ),
    app_commands.Choice(
        name="Eliminado",
        value="eliminado"
    )
])
@app_commands.checks.has_permissions(administrator=True)
async def resultado(
    interaction,
    jugador: discord.Member,
    resultado: app_commands.Choice[str],
    eliminaciones: int = 0
):

    datos = obtener_usuario(
        interaction.guild.id,
        jugador.id
    )

    victorias = datos[5]
    eliminaciones_actuales = datos[6]
    partidas = datos[7]

    partidas += 1
    eliminaciones_actuales += eliminaciones

    if resultado.value == "victoria":
        victorias += 1

    cursor.execute("""
    UPDATE usuarios
    SET victorias = ?,
        eliminaciones = ?,
        partidas = ?
    WHERE guild_id = ? AND user_id = ?
    """, (
        victorias,
        eliminaciones_actuales,
        partidas,
        interaction.guild.id,
        jugador.id
    ))

    db.commit()

    config = obtener_config(interaction.guild.id)

    canal_id = config["resultados"]

    if canal_id:

        canal = interaction.guild.get_channel(canal_id)

        if canal:

            embed = discord.Embed(
                title="RESULTADO HUNGER GAMES",
                color=discord.Color.dark_red()
            )

            embed.add_field(
                name="Jugador",
                value=jugador.mention
            )

            embed.add_field(
                name="Resultado",
                value=resultado.name
            )

            embed.add_field(
                name="Eliminaciones",
                value=str(eliminaciones)
            )

            await canal.send(embed=embed)

    await interaction.response.send_message(
        "Resultado registrado.",
        ephemeral=True
    )


# =========================================================
# DESINSCRIBIR
# =========================================================

@bot.tree.command(
    name="desinscribir",
    description="Desinscribe a un jugador"
)
@app_commands.describe(
    jugador="Jugador que será desinscrito"
)
@app_commands.checks.has_permissions(administrator=True)
async def desinscribir(
    interaction,
    jugador: discord.Member
):

    cursor.execute("""
    DELETE FROM inscripciones
    WHERE guild_id = ? AND user_id = ?
    """, (
        interaction.guild.id,
        jugador.id
    ))

    db.commit()

    await actualizar_participantes(
        interaction.guild
    )

    await interaction.response.send_message(
        f"{jugador.mention} ha sido desinscrito.",
        ephemeral=True
    )


# =========================================================
# RESET INSCRIPCIONES
# =========================================================

@bot.tree.command(
    name="resetinscripciones",
    description="Elimina todas las inscripciones"
)
@app_commands.checks.has_permissions(administrator=True)
async def resetinscripciones(interaction):

    cursor.execute("""
    DELETE FROM inscripciones
    WHERE guild_id = ?
    """, (interaction.guild.id,))

    db.commit()

    await actualizar_participantes(
        interaction.guild
    )

    await interaction.response.send_message(
        "Todas las inscripciones han sido eliminadas.",
        ephemeral=True
    )


# =========================================================
# MENSAJE
# =========================================================

@bot.tree.command(
    name="mensaje",
    description="Envía un mensaje a un canal"
)
@app_commands.describe(
    canal="Canal donde enviar el mensaje",
    mensaje="Mensaje que quieres enviar"
)
@app_commands.checks.has_permissions(administrator=True)
async def mensaje(
    interaction,
    canal: discord.TextChannel,
    mensaje: str
):

    await canal.send(mensaje)

    await interaction.response.send_message(
        f"Mensaje enviado a {canal.mention}.",
        ephemeral=True
    )


# =========================================================
# ERROR DE COMANDOS
# =========================================================

@bot.tree.error
async def error_handler(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):

        mensaje = (
            "No tienes permisos para utilizar este comando."
        )

    else:

        print("ERROR:", error)

        mensaje = (
            "Ocurrió un error al ejecutar el comando."
        )

    if interaction.response.is_done():

        await interaction.followup.send(
            mensaje,
            ephemeral=True
        )

    else:

        await interaction.response.send_message(
            mensaje,
            ephemeral=True
        )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    bot.add_view(InscribirseView())
    bot.add_view(TicketView())
    bot.add_view(CerrarTicketView())

    try:

        synced = await bot.tree.sync()

        print(
            f"Comandos sincronizados: {len(synced)}"
        )

    except Exception as e:

        print(
            f"Error sincronizando comandos: {e}"
        )

    print(
        f"Bot conectado como {bot.user}"
    )


# =========================================================
# INICIAR
# =========================================================

bot.run(TOKEN)
