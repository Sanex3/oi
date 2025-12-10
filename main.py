# discord_ticket_bot.py
"""
Полноценный Discord Ticket Bot
- Хранение настроек в settings.json (JSON)
- /settings через select-menu (вариант A)
- /deploy_ticket_message для развёртывания сообщения с кнопкой
- Полная тикет-система: modal → создание приватного канала → кнопки
- Фиолетовый embed-цвет: #46009E

ОПИСАНИЕ ПОЛЕЙ settings.json (создаётся автоматически при первом запуске):
- ticket_message_text: текст для сообщения с кнопкой
- ticket_button_channel_id: ID канала, куда бот будет отправлять сообщение с кнопкой
- ticket_category_id: ID категории для новых тикетов (или null)
- staff_role_id: ID роли модераторов
- accepted_role_id: ID роли, выдаваемой пользователю при окончательном принятии
- accept_message: текст ЛС при принятии
- reject_message: текст ЛС при отказе
"""

import json
import os
import discord
import logging
from discord.ext import commands
from discord import app_commands
from typing import Optional

# ---------------- CONFIG ----------------
SETTINGS_FILE = "settings.json"
EMBED_COLOR = 0x46009E  # фиолетовый #46009E
TOKEN = os.getenv("DISCORD_TOKEN")
# ----------------------------------------

# ----------------- SETTINGS IO -----------------

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        default = {
            "ticket_message_text": "Нажмите кнопку, чтобы открыть тикет:",
            "ticket_button_channel_id": None,
            "log_channel_id": None,
            "ticket_category_id": None,
            "staff_role_id": None,
            "accepted_role_id": None,
            "accept_message": "Ваш тикет был принят!",
            "reject_message": "Ваш тикет был отклонён.",
        }
        save_settings(default)
        return default
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_settings(data: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


settings = load_settings()

# --------------- BOT SETUP ----------------
intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- Helpers ----------------

def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator


def str_to_int_maybe(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


# ----------------- LOGGING -> Discord channel -----------------
class DiscordChannelHandler(logging.Handler):
    """
    Logging handler that sends formatted log records to a Discord channel.
    The channel id is read via a callable so it can be changed at runtime
    (reads from `settings`).
    """
    def __init__(self, channel_id_getter):
        super().__init__()
        self._channel_id_getter = channel_id_getter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            channel_id = self._channel_id_getter()
            if not channel_id:
                return
            try:
                cid = int(channel_id)
            except Exception:
                return
            bot.loop.create_task(self._send_to_channel(cid, f"[{record.levelname}] {message}"))
        except Exception:
            self.handleError(record)

    async def _send_to_channel(self, channel_id: int, message: str):
        try:
            ch = bot.get_channel(channel_id)
            if ch is None:
                try:
                    ch = await bot.fetch_channel(channel_id)
                except Exception:
                    return
            await ch.send(message)
        except Exception:
            pass


def send_log(level: str, message: str):
    """Backward-compatible wrapper: отправляет простой embed-лог с описанием `message`."""
    send_log_embed(level=level, title=None, description=message)


def send_log_embed(level: str = "info", title: Optional[str] = None, description: Optional[str] = None,
                   moderator: Optional[discord.abc.Snowflake] = None, owner_id: Optional[int] = None,
                   channel_id: Optional[int] = None, reason: Optional[str] = None):
    """
    Формирует embed-лог и отправляет его в `log_channel_id` (если настроен).
    Удобно вызывать с явными полями: moderator (User), owner_id (int), channel_id (int), reason (str).
    """
    try:
        target = settings.get("log_channel_id")
        if not target:
            return
        try:
            target_id = int(target)
        except Exception:
            return

        color_map = {
            "debug": 0x95A5A6,
            "info": 0x2ECC71,
            "warning": 0xE67E22,
            "error": 0xE74C3C,
            "critical": 0xC0392B,
        }
        lvl = (level or "info").lower()
        embed_color = color_map.get(lvl, 0x95A5A6)
        embed_title = title or (lvl.upper() if lvl else "LOG")
        embed = discord.Embed(title=embed_title, description=description or "", color=embed_color)
        # Дополнительные поля
        if moderator:
            try:
                embed.add_field(name="Модератор", value=f"{getattr(moderator, 'mention', str(moderator))} (id={getattr(moderator, 'id', moderator)})", inline=True)
            except Exception:
                embed.add_field(name="Модератор", value=str(moderator), inline=True)
        if owner_id:
            embed.add_field(name="Владелец", value=f"<@{owner_id}> (id={owner_id})", inline=True)
        if channel_id:
            embed.add_field(name="Канал", value=f"<#{channel_id}>", inline=True)
        if reason:
            embed.add_field(name="Причина", value=reason, inline=False)

        async def _send_embed():
            try:
                ch = bot.get_channel(target_id)
                if ch is None:
                    try:
                        ch = await bot.fetch_channel(target_id)
                    except Exception:
                        ch = None
                if ch:
                    await ch.send(embed=embed)
            except Exception:
                pass

        try:
            bot.loop.create_task(_send_embed())
        except Exception:
            # если loop недоступен — ничего не делаем
            pass
    except Exception:
        pass

# ----------------- MODALS -------------------
class TicketModal(discord.ui.Modal, title="Открыть тикет"):
    nick = discord.ui.TextInput(label="Ник в майнкрафте", min_length=3, max_length=50)
    age = discord.ui.TextInput(label="Возраст", min_length=1, max_length=2)
    purpose = discord.ui.TextInput(label="Чем будете заниматься?", style=discord.TextStyle.long, min_length=50, max_length=500)
    from_where = discord.ui.TextInput(label="Откуда узнали о нас?", min_length=1, max_length=50)
    read_rules = discord.ui.TextInput(label="Прочитали ли правила?", min_length=1, max_length=20)

    def __init__(self, author: discord.Member):
        super().__init__()
        self.author = author

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        # server-side validation (safety)
        nick_val = self.nick.value.strip() if hasattr(self.nick, "value") else str(self.nick).strip()
        age_val = self.age.value.strip() if hasattr(self.age, "value") else str(self.age).strip()
        purpose_val = self.purpose.value.strip() if hasattr(self.purpose, "value") else str(self.purpose).strip()
        from_where_val = self.from_where.value.strip() if hasattr(self.from_where, "value") else str(self.from_where).strip()
        read_rules_val = self.read_rules.value.strip() if hasattr(self.read_rules, "value") else str(self.read_rules).strip()

        if not (3 <= len(nick_val) <= 50):
            return await interaction.response.send_message("❌ Ник должен быть от 3 до 50 символов.", ephemeral=True)
        if not (1 <= len(age_val) <= 2) or (not age_val.isdigit()):
            return await interaction.response.send_message("❌ Возраст должен быть числом из 1-2 цифр.", ephemeral=True)
        if not (50 <= len(purpose_val) <= 500):
            return await interaction.response.send_message("❌ Поле 'Чем будете заниматься?' должно содержать от 50 до 500 символов.", ephemeral=True)
        if not (1 <= len(from_where_val) <= 50):
            return await interaction.response.send_message("❌ Поле 'Откуда узнали' должно содержать от 1 до 50 символов.", ephemeral=True)
        if not (1 <= len(read_rules_val) <= 20):
            return await interaction.response.send_message("❌ Поле 'Прочитали ли правила?' должно содержать от 1 до 20 символов.", ephemeral=True)

        # Настройки
        staff_role_id = settings.get("staff_role_id")
        category_id = settings.get("ticket_category_id")

        # Права: видит только владелец, стff и бот
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.author: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        if staff_role_id:
            role = guild.get_role(int(staff_role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        category = guild.get_channel(int(category_id)) if category_id else None

        channel_name = f"ticket-{self.author.name}"[:90]
        channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites, category=category, topic=f"ticket_owner:{self.author.id}")

        info_text = (
            f"**Ник в майнкрафте:** {nick_val}\n"
            f"**Возраст:** {age_val}\n"
            f"**Чем будет заниматься:** {purpose_val}\n"
            f"**Откуда узнал:** {from_where_val}\n"
            f"**Прочитал правила:** {read_rules_val}"
        )

        embed = discord.Embed(title="Новый тикет", description=f"{self.author.mention}, ваш тикет создан.", color=EMBED_COLOR)
        embed.add_field(name="Информация", value=info_text, inline=False)
        embed.set_footer(text=f"Тикет от {self.author.display_name} | ID: {self.author.id}")

        view = TicketInitialView(self.author, nick_val, age=age_val, purpose=purpose_val, from_where=from_where_val, read_rules=read_rules_val)
        await channel.send(content=self.author.mention, embed=embed, view=view)
        await interaction.response.send_message(f"Тикет создан: {channel.mention}", ephemeral=True)


class GenericValueModal(discord.ui.Modal):
    # Это модал для редактирования любой настройки, содержит одно большое поле
    def __init__(self, option_key: str, title: str = "Изменение настройки"):
        self.option_key = option_key
        super().__init__(title=title)
        # Если ожидается длинный текст — используем long
        style = discord.TextStyle.long if option_key.endswith("message") or option_key == "ticket_message_text" else discord.TextStyle.short
        self.value = discord.ui.TextInput(label=f"Новое значение для {option_key}", style=style, required=True)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        key = self.option_key
        new_val = self.value.value
        # Попытка привести ID-поля к int
        if key.endswith("_id"):
            conv = str_to_int_maybe(new_val)
            if conv is None:
                await interaction.response.send_message("❌ Значение должно быть числом (ID).", ephemeral=True)
                return
            settings[key] = conv
        else:
            settings[key] = new_val
        save_settings(settings)
        await interaction.response.send_message(f"✅ Настройка **{key}** обновлена.", ephemeral=True)


# ----------------- VIEWS / BUTTONS -----------------
class TicketInitialView(discord.ui.View):
    def __init__(self, owner: discord.Member, nick_text: str, age: Optional[str] = None,
                 purpose: Optional[str] = None, from_where: Optional[str] = None, read_rules: Optional[str] = None):
        super().__init__(timeout=None)
        self.owner = owner
        self.nick_text = nick_text
        self.age = age
        self.purpose = purpose
        self.from_where = from_where
        self.read_rules = read_rules
        self.taken_by: Optional[int] = None

    @discord.ui.button(label="Принять тикет", style=discord.ButtonStyle.primary, custom_id="ticket:take")
    async def take_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Проверка роли
        staff_role_id = settings.get("staff_role_id")
        if staff_role_id is None:
            return await interaction.response.send_message("❌ Роль модераторов не настроена.", ephemeral=True)

        allowed = False
        role = interaction.guild.get_role(int(staff_role_id))
        if role and role in interaction.user.roles:
            allowed = True
        if interaction.user.guild_permissions.administrator:
            allowed = True
        if not allowed:
            return await interaction.response.send_message("❌ У вас нет прав принять тикет.", ephemeral=True)

        if self.taken_by is not None:
            return await interaction.response.send_message("⚠ Этот тикет уже занят.", ephemeral=True)

        self.taken_by = interaction.user.id
        # Ограничиваем возможность писать для других модераторов: запрещаем send_messages для роли staff
        try:
            ch = interaction.channel
            if ch:
                if staff_role_id:
                    role = interaction.guild.get_role(int(staff_role_id))
                    if role:
                        # запретим отправку сообщений для роли модераторов
                        await ch.set_permissions(role, send_messages=False, view_channel=True, read_message_history=True)
                # явно разрешим отправку сообщений для модера, который взял тикет
                await ch.set_permissions(interaction.user, send_messages=True, view_channel=True, read_message_history=True)
                # убедимся, что владелец тикета по-прежнему может писать
                owner_member = interaction.guild.get_member(self.owner.id)
                if owner_member:
                    await ch.set_permissions(owner_member, send_messages=True, view_channel=True, read_message_history=True)
        except Exception:
            pass
        # Редактируем сообщение, показываем новую view (передаём данные тикета)
        await interaction.response.edit_message(view=TicketTakenView(
            self.owner,
            self.nick_text,
            self.taken_by,
            age=self.age,
            purpose=self.purpose,
            from_where=self.from_where,
            read_rules=self.read_rules
        ))


class TicketTakenView(discord.ui.View):
    def __init__(self, owner: discord.Member, nick_text: str, taker_id: int,
                 age: Optional[str] = None, purpose: Optional[str] = None,
                 from_where: Optional[str] = None, read_rules: Optional[str] = None):
        super().__init__(timeout=None)
        self.owner = owner
        self.nick_text = nick_text
        self.taker_id = taker_id
        self.age = age
        self.purpose = purpose
        self.from_where = from_where
        self.read_rules = read_rules

    def _is_taker_or_admin(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.taker_id or interaction.user.guild_permissions.administrator

    @discord.ui.button(label="Принять окончательно", style=discord.ButtonStyle.success, custom_id="ticket:accept_final")
    async def accept_final(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_taker_or_admin(interaction):
            return await interaction.response.send_message("⚠ Только модератор, взявший тикет, может это сделать.", ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(self.owner.id)
        if member:
            # Сменить ник
            try:
                await member.edit(nick=self.nick_text)
            except Exception:
                pass
            # Выдать роль
            accepted_role_id = settings.get("accepted_role_id")
            if accepted_role_id:
                role = guild.get_role(int(accepted_role_id))
                if role:
                    try:
                        await member.add_roles(role, reason="Тикет принят")
                    except Exception:
                        pass
            # Отправить ЛС в виде embed'а
            try:
                accept_text = settings.get("accept_message", None)
                description = "-# С уважением команда Abyss"
                # если в настройках указан текст — включим его перед подписью
                if accept_text:
                    description = f"{accept_text}\n\n{description}"
                embed = discord.Embed(title="Ваша заявка принята!", description=description, color=EMBED_COLOR)
                await member.send(embed=embed)
            except Exception:
                pass
        await interaction.response.send_message("✔ Тикет принят и пользователь уведомлён (если возможно).", ephemeral=True)

        # Логируем принятие тикета в канал логов (если указан)
        try:
            chan = interaction.channel
            taker = interaction.user
            owner_id = self.owner.id
            channel_id = chan.id if chan else None
            # structured embed log
            # Соберём текст тикета для логов
            try:
                ticket_text = (
                    f"**Ник:** {getattr(self, 'nick_text', '')}\n"
                    f"**Возраст:** {getattr(self, 'age', '')}\n"
                    f"**Чем будет заниматься:** {getattr(self, 'purpose', '')}\n"
                    f"**Откуда узнал:** {getattr(self, 'from_where', '')}\n"
                    f"**Прочитал правила:** {getattr(self, 'read_rules', '')}"
                )
            except Exception:
                ticket_text = None

            send_log_embed(level="info",
                           title="Заявка принята",
                           description=f"Тикет принят модератором {taker} (id={taker.id})\n\n{ticket_text or ''}",
                           moderator=taker,
                           owner_id=owner_id,
                           channel_id=channel_id)
            # Удаляем канал тикета сразу после принятия
            try:
                if chan:
                    await chan.delete()
            except Exception:
                pass
        except Exception:
            pass

    @discord.ui.button(label="Отклонить тикет", style=discord.ButtonStyle.danger, custom_id="ticket:reject")
    async def reject_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_taker_or_admin(interaction):
            return await interaction.response.send_message("⚠ Только модератор, взявший тикет, может отклонить.", ephemeral=True)

        owner_member = interaction.guild.get_member(self.owner.id)

        class RejectReasonModal(discord.ui.Modal, title="Причина отказа"):
            reason = discord.ui.TextInput(label="Причина (опционально)", style=discord.TextStyle.long, required=False)

            async def on_submit(inner_self, modal_interaction: discord.Interaction):
                msg = settings.get("reject_message", "Ваш тикет был отклонён.")
                if inner_self.reason.value:
                    msg = f"{msg}\n\n**Причина:** {inner_self.reason.value}"
                try:
                    if owner_member:
                        # отправляем отклонение в embed
                        description = msg + "\n\n-# С уважением команда Abyss"
                        embed = discord.Embed(title="Ваша заявка отклонена!", description=description, color=EMBED_COLOR)
                        await owner_member.send(embed=embed)
                except Exception:
                    pass
                await modal_interaction.response.send_message("❌ Тикет отклонён. Игрок уведомлён (если возможно).", ephemeral=True)

                # Логируем отклонение тикета
                try:
                    taker = modal_interaction.user
                    owner_id = self.owner.id
                    ch_id = modal_interaction.channel.id if modal_interaction.channel else None
                    reason_text = inner_self.reason.value or ""
                    try:
                        ticket_text = (
                            f"**Ник:** {getattr(self, 'nick_text', '')}\n"
                            f"**Возраст:** {getattr(self, 'age', '')}\n"
                            f"**Чем будет заниматься:** {getattr(self, 'purpose', '')}\n"
                            f"**Откуда узнал:** {getattr(self, 'from_where', '')}\n"
                            f"**Прочитал правила:** {getattr(self, 'read_rules', '')}"
                        )
                    except Exception:
                        ticket_text = None

                    send_log_embed(level="warning",
                                   title="Заявка отклонена",
                                   description=f"Тикет отклонён модератором {taker} (id={taker.id})\n\n{ticket_text or ''}",
                                   moderator=taker,
                                   owner_id=owner_id,
                                   channel_id=ch_id,
                                   reason=reason_text)
                    # Удаляем канал тикета сразу после отклонения
                    try:
                        if modal_interaction.channel:
                            await modal_interaction.channel.delete()
                    except Exception:
                        pass
                except Exception:
                    pass

        await interaction.response.send_modal(RejectReasonModal())

    @discord.ui.button(label="Удалить тикет", style=discord.ButtonStyle.secondary, custom_id="ticket:delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_taker_or_admin(interaction):
            return await interaction.response.send_message("⚠ Только модератор, взявший тикет, может удалить канал.", ephemeral=True)
        await interaction.response.send_message("Канал удаляется...", ephemeral=True)
        try:
            await interaction.channel.delete()
        except Exception:
            pass

    @discord.ui.button(label="Добавить модератора", style=discord.ButtonStyle.secondary, custom_id="ticket:add_moderator")
    async def add_moderator(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_taker_or_admin(interaction):
            return await interaction.response.send_message("⚠ Только модератор, взявший тикет, может это сделать.", ephemeral=True)

        class AddModeratorModal(discord.ui.Modal, title="Добавить модератора в тикет"):
            moderator = discord.ui.TextInput(label="ID или упоминание модератора", style=discord.TextStyle.short, required=True, max_length=100)

            async def on_submit(inner_self, modal_interaction: discord.Interaction):
                raw = inner_self.moderator.value.strip()
                # извлекаем первое числовое вхождение (ID)
                import re
                m = re.search(r"\d{17,20}", raw)
                if not m:
                    await modal_interaction.response.send_message("❌ Не удалось распознать ID пользователя.", ephemeral=True)
                    return
                try:
                    mid = int(m.group(0))
                except Exception:
                    await modal_interaction.response.send_message("❌ Неверный ID.", ephemeral=True)
                    return

                guild = modal_interaction.guild
                member = guild.get_member(mid)
                if member is None:
                    try:
                        member = await guild.fetch_member(mid)
                    except Exception:
                        member = None
                if member is None:
                    await modal_interaction.response.send_message("❌ Пользователь не найден на сервере.", ephemeral=True)
                    return

                ch = modal_interaction.channel
                try:
                    # Разрешаем выбранному модератору писать в канале
                    await ch.set_permissions(member, send_messages=True, view_channel=True, read_message_history=True)
                    # Отправляем сообщение в канал с упоминанием
                    await ch.send(f"{member.mention} Вы были добавлены в тикет {ch.mention}")
                    await modal_interaction.response.send_message("✔ Модератор добавлен в тикет.", ephemeral=True)
                    # Логируем добавление модератора
                    try:
                        send_log_embed(level="info",
                                       title="Модератор добавлен в тикет",
                                       description=f"Пользователь {member.mention} добавлен в тикет пользователем {modal_interaction.user} (id={modal_interaction.user.id})",
                                       moderator=member,
                                       channel_id=ch.id)
                    except Exception:
                        pass
                except Exception:
                    await modal_interaction.response.send_message("❌ Не удалось установить права или отправить сообщение.", ephemeral=True)

        await interaction.response.send_modal(AddModeratorModal())


# ----------------- Open Ticket View -----------------
class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Открыть тикет", style=discord.ButtonStyle.primary, custom_id="open:ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal(interaction.user))


# ----------------- SETTINGS SELECT VIEW -----------------
class SettingsSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Текст сообщения с кнопкой", value="ticket_message_text", description="Текст, который отправляется с кнопкой 'Открыть тикет'"),
            discord.SelectOption(label="Канал для кнопки (ID)", value="ticket_button_channel_id", description="ID канала, куда бот отправит сообщение с кнопкой"),
            discord.SelectOption(label="Канал логов (ID)", value="log_channel_id", description="ID канала, куда бот будет отправлять логи"),
            discord.SelectOption(label="Категория тикетов (ID)", value="ticket_category_id", description="ID категории для создаваемых тикетов"),
            discord.SelectOption(label="Роль модераторов (ID)", value="staff_role_id", description="ID роли модераторов"),
            discord.SelectOption(label="Роль при принятии (ID)", value="accepted_role_id", description="ID роли, выдаваемой при принятии"),
            discord.SelectOption(label="Текст при принятии", value="accept_message", description="Текст, отправляемый в ЛС при принятии"),
            discord.SelectOption(label="Текст при отказе", value="reject_message", description="Текст, отправляемый в ЛС при отказе"),
        ]
        super().__init__(placeholder="Выберите настройку для редактирования...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # Открываем модал для выбранной настройки
        key = self.values[0]
        modal = GenericValueModal(option_key=key, title=f"Изменение: {key}")
        await interaction.response.send_modal(modal)


class SettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(SettingsSelect())

# ----------------- SLASH COMMANDS -----------------
@bot.tree.command(name="settings", description="Настройки тикет-системы (админы)")
@app_commands.checks.has_permissions(administrator=True)
async def settings_command(interaction: discord.Interaction):
    """Открывает select-menu для изменения настроек (вариант A)."""
    view = SettingsView()
    # Показываем текущее значение в embed
    embed = discord.Embed(title="Настройки тикетов", color=EMBED_COLOR)
    def fmt(k):
        v = settings.get(k)
        return f"`{v}`" if v is not None else "`не задано`"
    embed.add_field(name="Текст сообщения", value=fmt("ticket_message_text"), inline=False)
    embed.add_field(name="Канал для кнопки (ID)", value=fmt("ticket_button_channel_id"), inline=True)
    embed.add_field(name="Канал логов (ID)", value=fmt("log_channel_id"), inline=True)
    embed.add_field(name="Категория (ID)", value=fmt("ticket_category_id"), inline=True)
    embed.add_field(name="Роль модераторов (ID)", value=fmt("staff_role_id"), inline=True)
    embed.add_field(name="Роль при принятии (ID)", value=fmt("accepted_role_id"), inline=True)
    embed.add_field(name="Текст при принятии", value=fmt("accept_message"), inline=False)
    embed.add_field(name="Текст при отказе", value=fmt("reject_message"), inline=False)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="deploy_ticket_message", description="Развернуть сообщение с кнопкой для открытия тикета (админ)")
@app_commands.checks.has_permissions(administrator=True)
async def deploy_ticket_message(interaction: discord.Interaction):
    ch_id = settings.get("ticket_button_channel_id")
    if not ch_id:
        return await interaction.response.send_message("❌ Канал для сообщения не настроен (ticket_button_channel_id).", ephemeral=True)
    channel = interaction.guild.get_channel(int(ch_id))
    if channel is None:
        return await interaction.response.send_message("❌ Канал не найден.", ephemeral=True)
    embed = discord.Embed(title="Открыть тикет", description=settings.get("ticket_message_text", "Открыть тикет"), color=EMBED_COLOR)
    await channel.send(embed=embed, view=OpenTicketView())
    await interaction.response.send_message(f"✔ Сообщение с кнопкой отправлено в {channel.mention}.", ephemeral=True)


@bot.tree.command(name="test_log", description="Отправить тестовый лог в канал логов (админ)")
@app_commands.checks.has_permissions(administrator=True)
async def test_log(interaction: discord.Interaction):
    """Команда для тестирования отправки логов."""
    send_log_embed(level="debug", title="Тестовый лог", description=f"Test log from {interaction.user} (id={interaction.user.id})", moderator=interaction.user)
    await interaction.response.send_message("✔ Тестовый лог отправлен (если настроен канал).", ephemeral=True)


# ----------------- ERROR HANDLERS -----------------
@settings_command.error
async def settings_error(interaction: discord.Interaction, error):
    await interaction.response.send_message(f"Ошибка: {error}", ephemeral=True)

@deploy_ticket_message.error
async def deploy_error(interaction: discord.Interaction, error):
    await interaction.response.send_message(f"Ошибка: {error}", ephemeral=True)

# ----------------- STARTUP -----------------
@bot.event
async def on_ready():
    # если нужно — можно зарегистрировать persistent views здесь: bot.add_view(...)
    try:
        await bot.tree.sync()
    except Exception:
        pass
    # Настроим отправку логов в канал, если указан `log_channel_id` в settings
    try:
        log_channel_id = settings.get("log_channel_id")
        if log_channel_id:
            handler = DiscordChannelHandler(lambda: settings.get("log_channel_id"))
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
            handler.setFormatter(formatter)
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)
            if root_logger.level == logging.NOTSET:
                root_logger.setLevel(logging.INFO)
    except Exception:
        pass
    print(f"Bot ready: {bot.user} (ID: {bot.user.id})")


if __name__ == "__main__":
    if TOKEN == "REPLACE_WITH_YOUR_TOKEN":
        print("Пожалуйста, укажи токен в переменной TOKEN в файле перед запуском.")
    else:
        bot.run(TOKEN)
