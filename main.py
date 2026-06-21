import asyncio
import logging
import re
import json
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from collections import Counter

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile,
)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from config import API_TOKEN, ADMIN_ID, YOUGILE_WEBHOOK_SECRET, DISPATCHER_INBOUND_API_KEY, DISPATCHER_GROUP_ID
from tools.yougile_api import create_task, search_tasks_by_user, get_tasks_for_stats, get_column_name
from tools.dispatcher_api import (
    describe_dispatcher_config,
    dispatcher_inbound_record_id,
    dispatcher_inbound_ready,
    fetch_customer_order_status,
    fetch_dispatcher_status_for_user,
    find_history_entry,
    format_customer_order_history_items,
    format_customer_order_history_messages,
    format_customer_order_status_message,
    format_lead_status_block,
    format_profile_crm_snippet,
    format_dispatcher_result_for_admin,
    ping_dispatcher_integration,
    send_order_to_dispatcher,
)
from tools.dispatcher_profiles_import import sync_missing_maintenance_dispatcher_cards

import aiofiles

from fastapi import FastAPI, Request, HTTPException
import uvicorn

# ─── Настройка логирования ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── Рабочее время (для автоответчика) ───────────────────────────────────────
# Часовой пояс: Europe/Minsk (UTC+3)
WORK_TZ_HOURS = 3  # UTC+3 для Беларуси
WORK_START_HOUR = 8  # 08:00
WORK_END_HOUR = 20   # 20:00

# ─── Пути к данным ───────────────────────────────────────────────────────────
os.makedirs("data", exist_ok=True)
USER_FILE = "data/users.json"
ORDER_LOG = "data/orders.log"
COMPLETED_FILE = "data/completed_orders.json"

# ─── Инициализация файлов данных ─────────────────────────────────────────────
# ─── Резервная копия пользователей (для инициализации пустого Volume) ────────
DEFAULT_USERS = {
    "5567898807": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "вцьоащц", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375291472109", "last_order_id": None, "last_address": None, "ratings": []},
    "5185948718": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Ната", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375447408978", "last_order_id": None, "last_address": None, "ratings": []},
    "7599242480": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Козырева Майя", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375295034840", "last_order_id": None, "last_address": "Колодищи 2, ул. Рябиновая, д. 10", "ratings": []},
    "6445132705": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Татьяна", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375293608308", "last_order_id": None, "last_address": "Минская область, Дзержинский район, д. Каменка, ул. Центральная д. 7", "ratings": []},
    "449621760": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Гаврош", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375447779866", "last_order_id": None, "last_address": "Логойский р-н, Беларучский с/с, СТ Текстиль, уч. 23", "ratings": []},
    "586923354": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Виктор", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375296160955", "last_order_id": None, "last_address": "Логойский район ст малиновка 2001, солнечная 192", "ratings": []},
    "750303531": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Игорь", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375296317433", "last_order_id": None, "last_address": "СТ НИВА Ф 188", "ratings": []},
    "508334961": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Сергей", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375296772018", "last_order_id": None, "last_address": "Заславль ул Строительная2", "ratings": []},
    "650648039": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Ирина", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375293697683", "last_order_id": None, "last_address": "Раубичи земляничная 3", "ratings": []},
    "1243322312": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Вячеслав Глеб", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375296562038", "last_order_id": None, "last_address": "Марьяливо, улица Центральная 43А", "ratings": []},
    "486713249": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Павел", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375296465638", "last_order_id": None, "last_address": "Аг.Острошицы, ул. Парижской Коммуны,5А", "ratings": []},
    "460143593": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Александр", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375296499005", "last_order_id": None, "last_address": "Д.Чуденичи, Широкая 10", "ratings": []},
    "432775666": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Татьяна", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375296450385", "last_order_id": None, "last_address": "Колодищи, ул.Беловежская,7а", "ratings": []},
    "515325398": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Василий", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375296344480", "last_order_id": None, "last_address": "д. Дроздово, ул. Полевая, 19", "ratings": []},
    "814067080": {"joined": "2026-04-11T19:30:00", "username": None, "full_name": "Анна", "reminder_sent": False, "last_reminder_sent": None, "phone": "+375293101429", "last_order_id": None, "last_address": "СТ Чистая Надзея 7", "ratings": []},
}

def _init_data_files():
    """Инициализирует файлы данных без перезаписи рабочей базы."""
    os.makedirs("data", exist_ok=True)
    
    print(f"🐍 PWD: {os.getcwd()}")
    print(f"📂 Files in data/: {os.listdir('data')}")
    sys.stdout.flush()

    # Важно: не затираем users.json дефолтными данными при каждом спорном кейсе.
    # Дефолт используем только при полном отсутствии файла (пустой volume/первый старт).
    needs_seed_default = False
    if not os.path.exists(USER_FILE):
        print("⚠️ users.json не существует — создадим стартовый файл")
        needs_seed_default = True
    else:
        size = os.path.getsize(USER_FILE)
        print(f"📊 users.json размер: {size} байт")
        if size > 0:
            try:
                with open(USER_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                print(f"📄 users.json содержимое: {content[:100]}...")
                data = json.loads(content) if content else {}
                if isinstance(data, dict):
                    print(f"👥 Текущих пользователей: {len(data)}")
                else:
                    print("⚠️ users.json не объект JSON — данные не трогаем, проверьте вручную")
            except Exception as e:
                backup_file = f"{USER_FILE}.broken.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                try:
                    if os.path.exists(USER_FILE):
                        os.replace(USER_FILE, backup_file)
                    with open(USER_FILE, "w", encoding="utf-8") as f:
                        json.dump({}, f, ensure_ascii=False, indent=2)
                    print(f"⚠️ users.json повреждён: {e}")
                    print(f"🛟 Бэкап сохранён: {backup_file}")
                    print("✅ Создан новый пустой users.json (без автовосстановления дефолта)")
                except Exception as backup_err:
                    print(f"❌ Ошибка аварийного восстановления users.json: {backup_err}")

    if needs_seed_default:
        print("🔨 Создаём users.json из DEFAULT_USERS (первый запуск)")
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_USERS, f, ensure_ascii=False, indent=2)
        print(f"✅ users.json создан: {len(DEFAULT_USERS)} пользователей")
    else:
        print("✅ users.json в порядке")
    
    sys.stdout.flush()

# Вызываем до настройки логирования, используем print
_init_data_files()

# ─── Бот и диспетчер ─────────────────────────────────────────────────────────
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# ─── FSM состояния ───────────────────────────────────────────────────────────
class OrderForm(StatesGroup):
    category = State()  # Выбор категории услуги
    phone = State()
    comment = State()
    photo = State()  # Фото к заказу (имя и адрес — только из профиля / «⚙️ Настройки»)


class BroadcastForm(StatesGroup):
    message = State()


class RatingForm(StatesGroup):
    rating = State()


class ProfileSettingsForm(StatesGroup):
    editing_name = State()
    editing_phone = State()
    editing_address = State()


# ─── Категории услуг ────────────────────────────────────────────────────────
SERVICE_CATEGORIES = {
    "🔧 Ремонт": "Ремонт оборудования",
    "🏗️ Монтаж": "Монтажные работы",
    "🧹 Обслуживание": "Техническое обслуживание",
    "📋 Консультация": "Консультация специалиста",
}

# ─── Периодичность ТО (в месяцах) ──────────────────────────────────────────
MAINTENANCE_INTERVAL_MONTHS = 6


def category_kb():
    """Клавиатура с категориями услуг."""
    buttons = [[KeyboardButton(text=cat)] for cat in SERVICE_CATEGORIES.keys()]
    buttons.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def comment_step_kb() -> ReplyKeyboardMarkup:
    """Комментарий: крупные кнопки (удобнее, чем только inline)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭️ Без комментария")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def photo_step_kb() -> ReplyKeyboardMarkup:
    """Фото: крупная кнопка пропуска + отмена."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭️ Без фото")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def maintenance_reminder_kb():
    """Inline-клавиатура для напоминаний о ТО."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 Записаться на ТО", callback_data="maint_order")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="maint_profile")],
        [InlineKeyboardButton(text="⏰ Напомнить через 7 дней", callback_data="maint_snooze:7")],
    ])


def settings_kb():
    """Inline-клавиатура настроек профиля."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить имя", callback_data="settings_edit_name")],
        [InlineKeyboardButton(text="📱 Изменить телефон", callback_data="settings_edit_phone")],
        [InlineKeyboardButton(text="📍 Изменить адрес", callback_data="settings_edit_address")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings_back")],
    ])


def client_cabinet_inline_kb():
    """Быстрые действия — видны и на десктопе Telegram."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статус", callback_data="cabinet_status"),
            InlineKeyboardButton(text="📋 Заказы", callback_data="cabinet_orders"),
        ],
        [
            InlineKeyboardButton(text="🧾 Заказ", callback_data="cabinet_new_order"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="cabinet_settings"),
        ],
    ])


def admin_menu_kb():
    """Меню только для админа — без клиентских кнопок."""
    buttons = [
        [KeyboardButton(text="🛡️ Админ-панель")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="⚙️ Настройки")],
        [KeyboardButton(text="📊 Статус заказа"), KeyboardButton(text="📋 Мои заказы")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def main_menu_kb(user_data: dict = None):
    """Главное меню клиента."""
    buttons = [[KeyboardButton(text="🧾 Сделать заказ")]]
    buttons.append([KeyboardButton(text="🏠 Кабинет")])
    if user_data and user_data.get("phone"):
        buttons.append([KeyboardButton(text="🔄 Повторить заказ")])
    buttons.append([KeyboardButton(text="📋 Мои заказы")])
    buttons.append([KeyboardButton(text="📊 Статус заказа")])
    buttons.append([KeyboardButton(text="👤 Мой профиль")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


async def main_menu_kb_with_admin(user_id: str, user_data: dict = None):
    """Главное меню. Админ — только админ-кнопки, клиент — клиентские.
    Если user_data не передан — загружаем сами."""
    if user_data is None:
        users = await load_users()
        user_data = users.get(user_id, {})

    if str(user_id) == str(ADMIN_ID):
        return admin_menu_kb()

    buttons = [[KeyboardButton(text="🧾 Сделать заказ")]]
    buttons.append([KeyboardButton(text="🏠 Кабинет")])
    if user_data and user_data.get("phone"):
        buttons.append([KeyboardButton(text="🔄 Повторить заказ")])
    buttons.append([KeyboardButton(text="📋 Мои заказы")])
    buttons.append([KeyboardButton(text="📊 Статус заказа")])
    buttons.append([KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="⚙️ Настройки")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def admin_panel_kb():
    """Клавиатура админ-панели."""
    buttons = [
        [KeyboardButton(text="👥 Пользователи"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🔧 ТО статус"), KeyboardButton(text="✅ Отметить ТО")],
        [KeyboardButton(text="📦 Заказы"), KeyboardButton(text="📢 Рассылка")],
        [KeyboardButton(text="📥 Экспорт CSV")],
        [KeyboardButton(text="🔙 Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


async def load_completed_orders() -> set:
    """Загружает ID выполненных заказов."""
    try:
        if os.path.exists(COMPLETED_FILE):
            async with aiofiles.open(COMPLETED_FILE, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
                return set(data)
    except Exception:
        pass
    return set()


async def save_completed_orders(completed: set):
    """Сохраняет ID выполненных заказов."""
    async with aiofiles.open(COMPLETED_FILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(list(completed), ensure_ascii=False))


def parse_orders_from_log(log_content: str) -> list:
    """Парсит заказы из лога. Возвращает список dict."""
    orders = []
    pattern = r"(📦 <b>Новый заказ</b>.*?id: <code>(\d+)</code>\))"
    for match in re.finditer(pattern, log_content, re.DOTALL):
        order_text = match.group(1).strip()
        user_id = match.group(2)
        # Извлекаем имя клиента
        name_match = re.search(r"👤 Имя: (.+?)\n", order_text)
        phone_match = re.search(r"📱 Телефон: (.+?)\n", order_text)
        address_match = re.search(r"📍 Адрес: (.+?)\n", order_text)
        category_match = re.search(r"📦 <b>Новый заказ</b> \| (.+?)\n", order_text)
        orders.append({
            "id": len(orders) + 1,
            "user_id": user_id,
            "name": name_match.group(1) if name_match else "—",
            "phone": phone_match.group(1) if phone_match else "—",
            "address": address_match.group(1) if address_match else "—",
            "category": category_match.group(1) if category_match else "—",
            "text": order_text,
        })
    return list(reversed(orders))  # Новые сверху


def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )


def rating_kb():
    """Клавиатура для оценки качества."""
    buttons = [
        [
            InlineKeyboardButton(text="⭐ 1", callback_data="rate:1"),
            InlineKeyboardButton(text="⭐ 2", callback_data="rate:2"),
            InlineKeyboardButton(text="⭐ 3", callback_data="rate:3"),
        ],
        [
            InlineKeyboardButton(text="⭐ 4", callback_data="rate:4"),
            InlineKeyboardButton(text="⭐ 5", callback_data="rate:5"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── Утилиты ─────────────────────────────────────────────────────────────────
def phone_is_valid(phone: str) -> bool:
    """Проверяет, что телефон содержит 10–15 цифр (поддержка BY/RU номеров)."""
    digits = re.sub(r"\D", "", phone)
    return 10 <= len(digits) <= 15


# Слова «пропустить фото» — иначе любой текст на шаге фото завершал заказ по ошибке
_SKIP_PHOTO_TEXT = frozenset(
    {"пропустить", "нет", "-", "без фото", "не надо", "далее", "skip", "ок", "no", "⏭️ без фото"},
)


def normalize_phone(phone: str) -> str:
    """Нормализует телефон. Для BY: +375XXXXXXXXX."""
    digits = re.sub(r"\D", "", phone)
    # Если начинается с 8 и 12 цифр (Беларусь) → +375
    if len(digits) == 12 and digits[0] == "8":
        digits = "375" + digits[1:]
    # Если 9 цифр (Беларусь без кода) → +375
    if len(digits) == 9:
        digits = "375" + digits
    # Если начинается с 8 и 11 цифр (Россия) → +7
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    # Если 10 цифр (Россия без кода) → +7
    if len(digits) == 10:
        digits = "7" + digits
    return "+" + digits


def _is_placeholder_display_name(value: str | None) -> bool:
    """Пустое имя или «заглушка» вроде одного дефиса — не использовать в заголовке заказа."""
    if value is None:
        return True
    t = value.strip()
    if not t:
        return True
    compact = t.replace(" ", "").replace("\u00a0", "").replace("\u2009", "")
    return compact in ("-", "—", "–", "―", "...", "…")


def display_contact_name_for_order(message: types.Message, prof: dict) -> str:
    """Имя в заказе: профиль → имя в Telegram → @username → «Клиент …»."""
    raw = prof.get("full_name")
    if isinstance(raw, str) and not _is_placeholder_display_name(raw):
        return raw.strip()
    fn = (message.from_user.full_name or "").strip()
    if fn and not _is_placeholder_display_name(fn):
        return fn
    un = (message.from_user.username or "").strip()
    if un:
        return f"@{un}"
    return f"Клиент {message.from_user.id}"


def is_work_time() -> bool:
    """Проверяет, находится ли текущее время в рабочем диапазоне."""
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.replace(tzinfo=timezone.utc)  # UTC
    # Для простоты используем UTC; если нужно — добавьте смещение
    hour = now_local.hour
    return WORK_START_HOUR <= hour < WORK_END_HOUR


def get_last_order(user_id: str) -> dict | None:
    """Извлекает последний заказ пользователя из лога."""
    try:
        with open(ORDER_LOG, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    # Ищем заказы по ID пользователя
    pattern = rf"🆔 Клиент:.*\(id: <code>{user_id}</code>\)"
    matches = list(re.finditer(pattern, content))
    if not matches:
        return None

    last_match = matches[-1]
    # Ищем начало этого заказа (📦 новый или 🔄 повторный)
    start_pkg = content.rfind("📦", 0, last_match.start())
    start_rep = content.rfind("🔄", 0, last_match.start())
    start = max(start_pkg, start_rep)
    if start == -1:
        start = last_match.start() - 200

    order_text = content[start:last_match.end()].strip()
    return {"text": order_text}


# ─── Асинхронная работа с пользователями ─────────────────────────────────────
_users_lock = asyncio.Lock()
_users_cache: dict = {}


async def load_users() -> dict:
    """Асинхронная загрузка пользователей с кэшированием."""
    global _users_cache
    if _users_cache:
        return _users_cache

    try:
        async with aiofiles.open(USER_FILE, "r", encoding="utf-8") as f:
            content = await f.read()
            _users_cache = json.loads(content)
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при загрузке users.json: {e}")
        _users_cache = {}

    return _users_cache


async def save_users(users: dict):
    """Асинхронное сохранение пользователей с блокировкой."""
    global _users_cache
    async with _users_lock:
        _users_cache = users
        tmp_file = USER_FILE + ".tmp"
        try:
            async with aiofiles.open(tmp_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(users, ensure_ascii=False, indent=2))
            if os.path.exists(USER_FILE):
                os.replace(tmp_file, USER_FILE)
            else:
                os.rename(tmp_file, USER_FILE)
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении users.json: {e}")
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
            raise


async def update_user_field(user_id: str, field: str, value):
    """Обновляет одно поле пользователя."""
    users = await load_users()
    if user_id in users:
        users[user_id][field] = value
        await save_users(users)


async def prompt_phone_step(message: types.Message, user_id: str) -> None:
    """Предлагаем сохранённый телефон или просим ввести."""
    users = await load_users()
    user_data = users.get(user_id, {}) or {}
    saved_phone = user_data.get("phone")
    if saved_phone:
        await message.answer(
            f"Ваш телефон: <b>{saved_phone}</b>?\n"
            "Введите новый или отправьте «Да»:",
            reply_markup=cancel_kb(),
        )
    else:
        await message.answer(
            "Введите ваш телефон:\n"
            "<i>(формат: +375XXXXXXXXX или 8XXXXXXXXXX)</i>",
            reply_markup=cancel_kb(),
        )


async def prompt_comment_after_phone(message: types.Message, state: FSMContext, user_id: str) -> bool:
    """После телефона: адрес должен быть в профиле, затем шаг комментария."""
    users = await load_users()
    raw = (users.get(user_id, {}) or {}).get("last_address")
    if isinstance(raw, str) and raw.strip():
        await state.set_state(OrderForm.comment)
        pdata = users.get(user_id, {}) or {}
        pphone = (pdata.get("phone") or "").strip()
        st = await state.get_data()
        cur_phone = (st.get("phone") or "").strip()
        if pphone and cur_phone == pphone:
            await message.answer(f"📱 Телефон в заказе: <b>{pphone}</b> (из настроек).")
        await message.answer(
            "📝 <b>Шаг 1 из 2</b> — комментарий\n"
            "Напишите текст или нажмите «⏭️ Без комментария».",
            reply_markup=comment_step_kb(),
        )
        return True
    await state.clear()
    await message.answer(
        "Чтобы оформить заказ, укажите в профиле <b>адрес объекта</b>:\n"
        "«⚙️ Настройки» → «📍 Изменить адрес».\n\n"
        "Нажмите кнопку ниже — откроются настройки:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⚙️ Открыть настройки", callback_data="order_open_settings")]],
        ),
    )
    return False


# ─── Миграция старого формата ────────────────────────────────────────────────
async def migrate_old_format():
    """Миграция users.json из старого формата."""
    users = await load_users()
    migrated = False
    for uid, data in list(users.items()):
        if isinstance(data, str):
            users[uid] = {
                "joined": data,
                "username": None,
                "full_name": None,
                "reminder_sent": False,
                "last_reminder_sent": None,
                "phone": None,
                "last_order_id": None,
                "ratings": [],
            }
            migrated = True
        elif isinstance(data, dict):
            for key, default in [
                ("reminder_sent", False),
                ("last_reminder_sent", None),
                ("phone", None),
                ("last_order_id", None),
                ("last_address", None),
                ("ratings", []),
            ]:
                if key not in data:
                    data[key] = default
                    migrated = True
            if "joined" not in data:
                data["joined"] = datetime.now().isoformat()
                migrated = True

    if migrated:
        await save_users(users)
        logger.info("✅ Миграция users.json завершена")


# ─── Проверка при запуске ────────────────────────────────────────────────────
def check_startup():
    """Проверяет обязательные параметры."""
    if ADMIN_ID is None:
        logger.warning("⚠️ ADMIN_ID не задан! Бот не сможет уведомлять администратора.")
    else:
        logger.info(f"✅ ADMIN_ID: {ADMIN_ID}")
    if dispatcher_inbound_ready():
        logger.info("✅ Диспетчер: интеграция включена — %s", describe_dispatcher_config())
    else:
        logger.warning(
            "⚠️ Диспетчер: заказы пойдут только в YouGile! %s",
            describe_dispatcher_config(),
        )


async def _notify_admin_dispatcher_result(disp: dict, *, context: str) -> None:
    """Уведомить админа о любом исходе (в т.ч. skipped — раньше молчали)."""
    if ADMIN_ID is None:
        return
    if disp.get("ok") and dispatcher_inbound_record_id(disp):
        return
    try:
        await bot.send_message(
            ADMIN_ID,
            f"{context}\n{format_dispatcher_result_for_admin(disp)}",
        )
    except Exception as e:
        logger.error("Не удалось уведомить админа о диспетчере: %s", e)


async def finalize_repeat_order(
    message: types.Message,
    *,
    name: str,
    phone: str,
    address: str,
    comment: str,
    category: str,
    user_data: dict,
) -> None:
    """Отправка повторного заказа: лог, диспетчер, YouGile, ответ клиенту."""
    user_id = str(message.from_user.id)
    summary = (
        f"🔄 <b>{category}</b>\n"
        f"👤 Имя: {name}\n"
        f"📱 Телефон: {phone}\n"
        f"📍 Адрес: {address}\n"
        f"💬 Комментарий: {comment}\n"
        f"🆔 Клиент: {message.from_user.full_name} (id: <code>{user_id}</code>)"
    )

    if ADMIN_ID is not None:
        try:
            await bot.send_message(ADMIN_ID, summary)
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить админа: {e}")

    async with aiofiles.open(ORDER_LOG, "a", encoding="utf-8") as f:
        await f.write(summary + "\n\n")

    disp = send_order_to_dispatcher(
        category=category,
        name=name,
        phone=phone,
        address=address,
        comment=comment,
        telegram_user_id=user_id,
        telegram_full_name=message.from_user.full_name or name,
    )
    task: dict = {}
    yougile_err: Exception | None = None
    try:
        task = create_task(title=f"{category} от {name}", description=summary)
    except Exception as e:
        logger.exception("❌ Ошибка при создании задачи в YouGile")
        yougile_err = e

    await _notify_admin_dispatcher_result(disp, context=f"🔄 {category}")

    lines = ["✅ Повторный заказ принят!"]
    if disp.get("ok") and dispatcher_inbound_record_id(disp):
        if disp.get("leadId"):
            lines.append(f"📥 Диспетчер (заявка): <code>{disp['leadId']}</code>")
        else:
            lines.append(f"📋 Диспетчер: <code>{disp['taskId']}</code>")
        _dg = disp.get("groupId")
        if _dg:
            lines.append(f"📂 Группа в Диспетчере (id): <code>{_dg}</code> — откройте вкладку «Заявки» в этой группе.")
    elif not disp.get("skipped"):
        lines.append("⚠️ Диспетчер: не удалось создать заявку (проверьте логи и .env).")
    if task.get("id"):
        lines.append(f"📋 YouGile: <code>{task['id']}</code>")
    elif yougile_err:
        lines.append(f"⚠️ YouGile: {yougile_err}")
    if not disp.get("ok") and not task.get("id") and not disp.get("skipped"):
        lines = [
            "⚠️ Заказ зафиксирован у админа, но не записан ни в диспетчер, ни в YouGile.",
            f"Ошибка YouGile: {yougile_err}" if yougile_err else "",
        ]
        lines = [x for x in lines if x]

    await message.answer(
        "\n".join(lines),
        reply_markup=await main_menu_kb_with_admin(user_id, user_data),
    )
    await dp.storage.clear(chat_id=message.chat.id, user_id=message.from_user.id)


async def show_client_cabinet(message: types.Message, user_id: str, user_data: dict) -> None:
    crm_block = ""
    if dispatcher_inbound_ready():
        phone_norm = normalize_phone(user_data.get("phone") or "") if user_data.get("phone") else None
        try:
            disp = fetch_dispatcher_status_for_user(
                phone=phone_norm,
                telegram_user_id=user_id,
                group_id=DISPATCHER_GROUP_ID or None,
            )
            crm_block = format_profile_crm_snippet(disp)
        except Exception:
            crm_block = "📌 <b>Заказ:</b> CRM временно недоступна"
    await message.answer(
        f"🏠 <b>Личный кабинет</b>\n\n{crm_block}\n\nВыберите действие:",
        reply_markup=client_cabinet_inline_kb(),
    )


# ─── Фича 6: Автоответчик вне рабочего времени ──────────────────────────────
async def check_work_hours(message: types.Message) -> bool:
    """Если вне рабочего времени — предупреждает и возвращает True."""
    if not is_work_time():
        await message.answer(
            "🌙 Спасибо за обращение! Сейчас мы не работаем.\n"
            f"🕐 Наши часы работы: {WORK_START_HOUR}:00 — {WORK_END_HOUR}:00\n"
            "Ваш заказ будет обработан в ближайшее рабочее время."
        )
        return True
    return False


# ═════════════════════════════════════════════════════════════════════════════
# ─── Обработчики команд ─────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

@dp.message(Command("dispatcher_ping"))
async def cmd_dispatcher_ping(message: types.Message):
    """Проверка связи бот → API диспетчера (inbound-order)."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return
    await message.answer("Проверяю диспетчер…")
    disp = await asyncio.to_thread(ping_dispatcher_integration)
    lines = [format_dispatcher_result_for_admin(disp), "", "<i>Конфиг:</i>", describe_dispatcher_config()]
    await message.answer("\n".join(lines))


@dp.message(Command("restore"))
async def cmd_restore(message: types.Message):
    """Ручное восстановление базы пользователей."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return

    global _users_cache
    _users_cache = DEFAULT_USERS.copy()

    try:
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_USERS, f, ensure_ascii=False, indent=2)
        await message.answer(f"✅ База восстановлена! {len(DEFAULT_USERS)} пользователей.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    logger.info(f"👤 /start от user_id={user_id}, full_name={message.from_user.full_name}")
    # Очищаем FSM — чтобы админ не оставался в состоянии заказа
    await state.clear()
    users = await load_users()

    # Если пользователь уже был — не перезаписываем телефон
    if user_id in users:
        users[user_id]["joined"] = datetime.now().isoformat()
        users[user_id]["username"] = message.from_user.username
        if users[user_id].get("full_name") is None:
            users[user_id]["full_name"] = message.from_user.full_name
    else:
        users[user_id] = {
            "joined": datetime.now().isoformat(),
            "username": message.from_user.username,
            "full_name": message.from_user.full_name,
            "reminder_sent": False,
            "last_reminder_sent": None,
            "phone": None,
            "last_order_id": None,
            "ratings": [],
        }
    await save_users(users)

    user_data = users[user_id]
    next_maint = calc_next_maintenance(user_data.get("joined"))

    # Админ — без клиентского приветствия
    if str(user_id) == str(ADMIN_ID):
        maint_info = ""
        if next_maint:
            maint_info = f"\n📅 Следующее ТО: {next_maint.strftime('%d.%m.%Y')}"
        await message.answer(
            f"Здравствуйте, Админ! 🛡️{maint_info}\n"
            "Управляйте ботом через панель ниже.",
            reply_markup=await main_menu_kb_with_admin(str(message.from_user.id), user_data)
        )
    else:
        maint_info = ""
        if next_maint:
            maint_info = f"\n📅 Следующее ТО: {next_maint.strftime('%d.%m.%Y')}"
        await message.answer(
            f"Привет, {message.from_user.full_name}! 👋\n"
            "Я приму ваш заказ и передам менеджеру.\n"
            "«🏠 Кабинет» — статус, заказы и настройки в одном месте.\n"
            "Или нажмите «🧾 Сделать заказ», чтобы оформить заявку."
            f"{maint_info}",
            reply_markup=await main_menu_kb_with_admin(str(message.from_user.id), user_data)
        )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    users = await load_users()
    user_data = users.get(str(message.from_user.id), {})

    # Информация о следующем ТО
    next_maint = calc_next_maintenance(user_data.get("joined"))
    maint_info = ""
    if next_maint:
        days = (next_maint - datetime.now()).days
        if days <= 0:
            maint_info = f"\n\n🔧 <b>ТО просрочено!</b> Рекомендуется записаться на обслуживание."
        else:
            maint_info = f"\n\n📅 <b>Следующее ТО:</b> {next_maint.strftime('%d.%m.%Y')} (через {days} дн.)"

    await message.answer(
        "📋 <b>Доступные команды:</b>\n\n"
        "/start — Начать работу с ботом\n"
        "/help — Показать это сообщение\n"
        "/cabinet — Личный кабинет (статус, заказы, настройки)\n"
        "/profile — Мой профиль и дата ТО\n"
        "/status — Статус последнего заказа\n"
        "/rate — Оценить качество обслуживания\n\n"
        "🧾 <b>Кнопки:</b>\n"
        "• Сделать заказ — оформить заявку\n"
        "• Кабинет — статус, заказы и настройки\n"
        "• Повторить заказ — быстро заказать то же самое\n"
        "• Мои заказы — история заказов\n"
        "• Статус заказа — этап заявки и работ\n\n"
        "🕐 Часы работы: 08:00 — 20:00\n"
        f"{maint_info}",
        reply_markup=await main_menu_kb_with_admin(str(message.from_user.id), user_data)
    )


@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    """Показывает профиль пользователя или админа."""
    users = await load_users()
    user_id = str(message.from_user.id)
    user_data = users.get(user_id, {})

    if not user_data:
        await message.answer("⚠️ Вы ещё не зарегистрированы. Нажмите /start")
        return

    menu_kb = await main_menu_kb_with_admin(user_id, user_data)

    # Админ — отдельный профиль
    if str(user_id) == str(ADMIN_ID):
        name = user_data.get("full_name", "—")
        phone = user_data.get("phone", "—")
        joined = user_data.get("joined", "—")[:10]
        address = user_data.get("last_address", "—")
        ratings = user_data.get("ratings", [])
        avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else "нет оценок"
        blocked = "Да" if user_data.get("blocked") else "Нет"
        crm_block = ""
        if dispatcher_inbound_ready():
            phone_norm = normalize_phone(phone) if phone and phone != "—" else None
            try:
                disp = fetch_dispatcher_status_for_user(
                    phone=phone_norm,
                    telegram_user_id=user_id,
                    group_id=DISPATCHER_GROUP_ID or None,
                )
                crm_block = "\n\n" + format_profile_crm_snippet(disp)
            except Exception:
                crm_block = "\n\n📌 <b>Заказ:</b> CRM временно недоступна"

        text = (
            f"🛡️ <b>Профиль администратора</b>\n\n"
            f"Имя: {name}\n"
            f"ID: <code>{user_id}</code>\n"
            f"Телефон: {phone}\n"
            f"Адрес: {address}\n"
            f"Дата регистрации: {joined}\n"
            f"Средняя оценка: {avg_rating}\n"
            f"Заблокирован: {blocked}"
            f"{crm_block}"
        )
        await message.answer(text, reply_markup=menu_kb)
        await message.answer("👇 Быстрые действия", reply_markup=client_cabinet_inline_kb())
        return

    # Профиль клиента
    name = user_data.get("full_name", "—")
    phone = user_data.get("phone", "—")
    address = user_data.get("last_address", "—")
    joined = user_data.get("joined", "—")[:10]
    ratings = user_data.get("ratings", [])
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else "нет оценок"
    blocked = "🚫 Да" if user_data.get("blocked") else "Нет"

    next_maint = calc_next_maintenance(user_data.get("joined"))
    if next_maint:
        days = (next_maint - datetime.now()).days
        if days <= 0:
            maint_status = f"🔴 Просрочено на {abs(days)} дн."
        else:
            maint_status = f"🟢 Через {days} дн. ({next_maint.strftime('%d.%m.%Y')})"
    else:
        maint_status = "⚪ Не определено"

    crm_block = ""
    if dispatcher_inbound_ready():
        phone_norm = normalize_phone(phone) if phone and phone != "—" else None
        try:
            disp = fetch_dispatcher_status_for_user(
                phone=phone_norm,
                telegram_user_id=user_id,
                group_id=DISPATCHER_GROUP_ID or None,
            )
            crm_block = "\n\n" + format_profile_crm_snippet(disp)
        except Exception:
            crm_block = "\n\n📌 <b>Заказ:</b> CRM временно недоступна"

    text = (
        f"👤 <b>Мой профиль</b>\n\n"
        f"Имя: {name}\n"
        f"Телефон: {phone}\n"
        f"Адрес: {address}\n"
        f"Дата регистрации: {joined}\n"
        f"Средняя оценка: {avg_rating}\n"
        f"Заблокирован: {blocked}\n\n"
        f"🔧 <b>ТО скважины</b> (каждые {MAINTENANCE_INTERVAL_MONTHS} мес.):\n"
        f"Статус: {maint_status}"
        f"{crm_block}"
    )

    await message.answer(text, reply_markup=menu_kb)
    await message.answer("👇 Быстрые действия", reply_markup=client_cabinet_inline_kb())


# ─── Фича 2: Статус заказа ──────────────────────────────────────────────────
async def send_order_status(message: types.Message, user_id: str, user_data: dict | None = None):
    """Статус из диспетчера (CRM); клавиатура меню всегда прикрепляется."""
    if user_data is None:
        users = await load_users()
        user_data = users.get(user_id, {})
    menu_kb = await main_menu_kb_with_admin(user_id, user_data)
    phone = normalize_phone((user_data.get("phone") or "").strip()) if user_data.get("phone") else ""

    if dispatcher_inbound_ready():
        try:
            disp = fetch_customer_order_status(
                phone or None,
                telegram_user_id=user_id,
                group_id=DISPATCHER_GROUP_ID or None,
            )
        except Exception as e:
            logger.error("Dispatcher status lookup failed: %s", e)
            disp = {"ok": False, "found": False, "error": str(e)}

        if disp.get("ok") and disp.get("found"):
            text = format_customer_order_status_message(disp)
            if text:
                await message.answer(text, reply_markup=menu_kb)
                return

        if disp.get("ok") and not disp.get("found"):
            last_order = get_last_order(user_id)
            lines = ["📭 <b>Заявка в CRM пока не найдена.</b>", "Если заказ только что оформлен — подождите минуту и нажмите «📊 Статус заказа» снова."]
            if last_order:
                lines.append("")
                lines.append("📋 <b>Последний заказ в боте:</b>")
                lines.append("")
                lines.append(last_order["text"])
            await message.answer("\n".join(lines), reply_markup=menu_kb)
            return

        err = disp.get("error") or disp.get("reason") or "ошибка связи"
        await message.answer(
            f"⚠️ Не удалось получить статус из диспетчера ({err}).\nПопробуйте позже или напишите менеджеру.",
            reply_markup=menu_kb,
        )
        return

    # Диспетчер не настроен — локальный лог / YouGile
    last_order = get_last_order(user_id)
    if last_order:
        await message.answer(
            "📋 <b>Ваш последний заказ:</b>\n\n"
            f"{last_order['text']}\n\n"
            "ℹ️ CRM диспетчера не подключена — точный этап заявки недоступен.",
            reply_markup=menu_kb,
        )
        return

    await message.answer("📭 У вас пока нет заказов.", reply_markup=menu_kb)


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    user_id = str(message.from_user.id)
    users = await load_users()
    user_data = users.get(user_id, {})
    await send_order_status(message, user_id, user_data)


@dp.message(F.text == "📊 Статус заказа")
async def btn_order_status(message: types.Message):
    user_id = str(message.from_user.id)
    users = await load_users()
    user_data = users.get(user_id, {})
    await send_order_status(message, user_id, user_data)


# ─── Фича 5: Статистика (только админ) ─────────────────────────────────────
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ может просматривать статистику.")
        return

    # Загружаем пользователей
    users = await load_users()
    total_users = len(users)

    # Считаем заказы из лога
    try:
        async with aiofiles.open(ORDER_LOG, "r", encoding="utf-8") as f:
            log_content = await f.read()
    except Exception:
        log_content = ""

    total_orders = log_content.count("📦 <b>Новый заказ</b>")

    # Статистика по категориям из YouGile
    try:
        tasks = get_tasks_for_stats()
        # Группируем по колонкам
        columns = Counter()
        for task in tasks:
            col = task.get("columnId", "unknown")
            columns[col] += 1
    except Exception as e:
        logger.error(f"Ошибка при получении статистики YouGile: {e}")
        columns = {}

    now = datetime.now()
    text = (
        f"📊 <b>Статистика бота</b>\n"
        f"📅 {now.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"📦 Заказов (лог): <b>{total_orders}</b>\n\n"
    )

    if columns:
        text += "📌 Задачи по колонкам (YouGile):\n"
        for col_id, count in columns.most_common(10):
            try:
                col_name = get_column_name(col_id)
            except Exception:
                col_name = col_id[:8] + "..."
            text += f"  • {col_name}: {count}\n"

    # Средний рейтинг
    ratings = []
    for u in users.values():
        if isinstance(u, dict) and u.get("ratings"):
            ratings.extend(u["ratings"])
    if ratings:
        avg_rating = sum(ratings) / len(ratings)
        text += f"\n⭐ Средний рейтинг: {avg_rating:.1f}/5 ({len(ratings)} оценок)"

    await message.answer(text)


# ─── Фича 3: Рассылка (только админ) ────────────────────────────────────────
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ может делать рассылки.")
        return

    await message.answer(
        "📢 <b>Режим рассылки</b>\n"
        "Отправьте сообщение, которое нужно разослать всем пользователям.\n"
        "Для отмены введите /cancel"
    )
    await state.set_state(BroadcastForm.message)


@dp.message(BroadcastForm.message)
async def process_broadcast(message: types.Message, state: FSMContext):
    # Проверка на отмену
    if message.text and message.text.strip().lower() in ("/cancel", "отмена", "назад"):
        await message.answer("❌ Рассылка отменена.")
        await state.clear()
        return

    users = await load_users()
    total = len(users)
    sent = 0
    failed = 0

    status_msg = await message.answer(f"📢 Рассылка... 0/{total}")

    for user_id, user_data in users.items():
        if isinstance(user_data, dict) and user_data.get("blocked"):
            continue
        try:
            # Копируем сообщение (поддерживает текст, фото, и т.д.)
            if message.text:
                await bot.send_message(int(user_id), message.text)
            sent += 1
        except Exception as e:
            await handle_send_error(e, user_id)
            failed += 1

        # Обновляем статус каждые 10 сообщений
        if (sent + failed) % 10 == 0:
            try:
                await status_msg.edit_text(f"📢 Рассылка... {sent + failed}/{total}")
            except Exception:
                pass

    await status_msg.edit_text(
        f"✅ Рассылка завершена!\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"👥 Всего: {total}"
    )
    await state.clear()


# ─── Админ: Отчёт о ТО ──────────────────────────────────────────────────────
@dp.message(Command("maintenance"))
async def cmd_maintenance(message: types.Message):
    """Показывает админу статус ТО всех пользователей."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return

    users = await load_users()
    now = datetime.now()
    overdue = []
    soon = []
    ok = []

    for user_id, user_data in sorted(users.items(), key=lambda x: x[1].get("joined", "")):
        if not isinstance(user_data, dict):
            continue
        name = user_data.get("full_name", "—")
        phone = user_data.get("phone", "—")
        joined_str = user_data.get("joined")
        next_maint = calc_next_maintenance(joined_str)

        if not next_maint:
            continue

        days_until = (next_maint - now).days
        reminder_sent = user_data.get("reminder_sent", False)

        if days_until <= 0:
            overdue.append(f"  🔴 {name} | {phone} | ТО просрочено ({abs(days_until)} дн.) | Напоминание: {'✅' if reminder_sent else '❌'}")
        elif days_until <= 30:
            soon.append(f"  🟡 {name} | {phone} | через {days_until} дн. ({next_maint.strftime('%d.%m.%Y')}) | Напоминание: {'✅' if reminder_sent else '❌'}")
        else:
            ok.append(f"  🟢 {name} | через {days_until} дн. ({next_maint.strftime('%d.%m.%Y')})")

    text = f"🔧 <b>Статус ТО</b> (интервал: {MAINTENANCE_INTERVAL_MONTHS} мес.):\n\n"

    if overdue:
        text += f"<b>⚠️ Просрочено ({len(overdue)})</b>:\n" + "\n".join(overdue) + "\n\n"
    if soon:
        text += f"<b>📅 Скоро ({len(soon)})</b>:\n" + "\n".join(soon[:10]) + "\n\n"
    if ok:
        text += f"<b>✅ В норме ({len(ok)})</b>:\n" + "\n".join(ok[:10])

    if len(ok) > 10:
        text += f"\n  ... и ещё {len(ok) - 10}"

    await message.answer(text)


# ─── Админ: Сброс напоминаний ───────────────────────────────────────────────
@dp.message(Command("reset_reminders"))
async def cmd_reset_reminders(message: types.Message):
    """Сбрасывает флаги reminder_sent у всех пользователей."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return

    users = await load_users()
    count = 0
    for user_id, user_data in users.items():
        if isinstance(user_data, dict) and user_data.get("reminder_sent"):
            users[user_id]["reminder_sent"] = False
            count += 1

    await save_users(users)
    await message.answer(f"✅ Сброшены напоминания у {count} пользователей.")


# ─── Админ: Заполнить адреса ────────────────────────────────────────────────
@dp.message(Command("fill_addresses"))
async def cmd_fill_addresses(message: types.Message):
    """Заполняет адреса пользователей из DEFAULT_USERS."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return

    users = await load_users()
    updated = 0
    for uid, default_data in DEFAULT_USERS.items():
        if uid in users and isinstance(users[uid], dict):
            addr = default_data.get("last_address")
            if addr and not users[uid].get("last_address"):
                users[uid]["last_address"] = addr
                updated += 1

    await save_users(users)
    await message.answer(f"✅ Заполнены адреса у {updated} пользователей.")


# ─── Реальные даты подключения из YouGile ──────────────────────────────────
# 9 пользователей с датами из активности YouGile
# 6 пользователей без истории — дата от последней известной + 1 неделя каждый
YOUGILE_TASK_DATES = {
    "7599242480": "2025-10-10T20:51:00",    # Козырева Майя
    "6445132705": "2025-10-16T23:56:00",    # Татьяна
    "750303531": "2025-11-19T14:16:00",     # Игорь
    "508334961": "2025-11-28T10:42:00",     # Сергей
    "650648039": "2025-11-29T21:22:00",     # Ирина
    "1243322312": "2025-12-09T15:40:00",    # Вячеслав Глеб
    "460143593": "2025-12-20T18:04:00",     # Александр
    "814067080": "2026-01-11T16:27:00",     # Анна
    "432775666": "2026-01-15T13:46:00",     # Татьяна (2)
    "5567898807": "2026-01-22T12:00:00",    # вцьоащц (+1 нед)
    "5185948718": "2026-01-29T12:00:00",    # Ната (+2 нед)
    "449621760":  "2026-02-05T12:00:00",    # Гаврош (+3 нед)
    "586923354":  "2026-02-12T12:00:00",    # Виктор (+4 нед)
    "486713249":  "2026-02-19T12:00:00",    # Павел (+5 нед)
    "515325398":  "2026-02-26T12:00:00",    # Василий (+6 нед)
}


# ─── Админ: Синхронизировать даты подключения из YouGile ───────────────────
@dp.message(Command("sync_dates"))
async def cmd_sync_dates(message: types.Message):
    """Обновляет даты подключения пользователей по данным из YouGile."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return

    users = await load_users()
    updated = 0
    lines = []

    for user_id, real_date in YOUGILE_TASK_DATES.items():
        if user_id in users and isinstance(users[user_id], dict):
            old_joined = users[user_id].get("joined", "")
            users[user_id]["joined"] = real_date
            updated += 1
            name = users[user_id].get("full_name", "—")
            lines.append(f"• {name}: {old_joined[:10]} → {real_date[:10]}")

    await save_users(users)

    text = f"✅ Синхронизированы даты у {updated} пользователей:\n" + "\n".join(lines)
    await message.answer(text)


# ─── Админ: Отметить ТО (заказ по телефону) ────────────────────────────────
@dp.message(F.text == "✅ Отметить ТО")
async def btn_mark_maintenance(message: types.Message):
    """Показать список пользователей для отметки ТО."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return

    users = await load_users()
    keyboard = []
    count = 0

    for uid, data in sorted(users.items(), key=lambda x: x[1].get("full_name", "")):
        if not isinstance(data, dict):
            continue
        name = data.get("full_name", "—")
        phone = data.get("phone", "")
        next_maint = calc_next_maintenance(data.get("joined"))
        if next_maint:
            days = (next_maint - datetime.now()).days
            status = "🔴" if days <= 0 else "🟡" if days <= 30 else "🟢"
        else:
            status = "⚪"

        keyboard.append([InlineKeyboardButton(
            text=f"{status} {name}",
            callback_data=f"maint_user:{uid}"
        )])
        count += 1

    await message.answer(
        f"✅ <b>Отметить ТО</b>\nВыберите пользователя:\n"
        f"🟢 В норме | 🟡 Скоро | 🔴 Просрочено",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@dp.callback_query(F.data.startswith("maint_user:"))
async def callback_confirm_maint(callback: types.CallbackQuery):
    """Подтверждение отметки ТО."""
    user_id = callback.data.split(":")[1]
    users = await load_users()
    user_data = users.get(user_id, {})
    name = user_data.get("full_name", "—")
    phone = user_data.get("phone", "—")
    next_maint = calc_next_maintenance(user_data.get("joined"))
    next_str = next_maint.strftime("%d.%m.%Y") if next_maint else "—"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"maint_confirm:{user_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="maint_cancel")],
    ])

    await callback.message.edit_text(
        f"Отметить ТО для:\n"
        f"👤 {name}\n"
        f"📱 {phone}\n"
        f"📅 Следующее ТО: {next_str}\n\n"
        "Дата ТО обновится на сегодня. Подтвердить?"
    )
    await callback.message.answer("⬆️ Подтвердите или отмените:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("maint_confirm:"))
async def callback_do_maint(callback: types.CallbackQuery):
    """Выполнить отметку ТО."""
    user_id = callback.data.split(":")[1]
    users = await load_users()

    if user_id not in users or not isinstance(users[user_id], dict):
        await callback.answer("Пользователь не найден!", show_alert=True)
        return

    now = datetime.now()
    users[user_id]["last_reminder_sent"] = now.isoformat()
    users[user_id]["reminder_sent"] = False
    users[user_id]["joined"] = now.isoformat()
    await save_users(users)

    name = users[user_id].get("full_name", "—")
    phone = users[user_id].get("phone", "—")
    next_to = now + timedelta(days=MAINTENANCE_INTERVAL_MONTHS * 30)

    await callback.message.edit_text(
        f"✅ ТО отмечено как проведённое:\n\n"
        f"👤 {name} ({user_id})\n"
        f"📱 {phone}\n"
        f"📅 Следующее ТО: {next_to.strftime('%d.%m.%Y')}"
    )
    await callback.answer("ТО отмечено!")


@dp.callback_query(F.data == "maint_cancel")
async def callback_cancel_maint(callback: types.CallbackQuery):
    await callback.message.edit_text("Отменено.")
    await callback.answer()


# ─── Callback-кнопки напоминаний о ТО ──────────────────────────────────────
@dp.callback_query(F.data == "maint_order")
async def cb_maint_order(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("🧾 Отлично! Выбирайте категорию услуги:")
    await state.set_state(OrderForm.category)
    await callback.message.answer(
        "Выберите тип услуги.\n"
        "<i>Данные из «⚙️ Настройки»; дальше комментарий и фото.</i>",
        reply_markup=category_kb(),
    )


@dp.callback_query(F.data == "maint_profile")
async def cb_maint_profile(callback: types.CallbackQuery):
    await callback.answer()
    await cmd_profile(callback.message)


@dp.callback_query(F.data.startswith("maint_snooze:"))
async def cb_maint_snooze(callback: types.CallbackQuery):
    days = int(callback.data.split(":")[1])
    user_id = str(callback.from_user.id)
    users = await load_users()
    if user_id in users and isinstance(users[user_id], dict):
        # Сдвигаем дату следующего напоминания
        new_reminder_date = (datetime.now() + timedelta(days=days)).isoformat()
        users[user_id]["last_reminder_sent"] = new_reminder_date
        await save_users(users)
    await callback.message.edit_text(f"⏰ Хорошо! Напомню через {days} дн.")
    await callback.answer("Напоминание отложено!")


# ─── Админ: Экспорт пользователей ───────────────────────────────────────────
@dp.message(Command("export"))
async def cmd_export(message: types.Message):
    """Экспорт всех пользователей в CSV-файл."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return

    users = await load_users()
    csv_lines = ["ID,Имя,Телефон,Дата регистрации,Напоминание,Ср. рейтинг"]

    for user_id, user_data in users.items():
        if not isinstance(user_data, dict):
            continue
        name = user_data.get("full_name", "").replace(",", ";")
        phone = user_data.get("phone", "—")
        joined = user_data.get("joined", "—")[:10]
        reminder = "✅" if user_data.get("reminder_sent") else "❌"
        ratings = user_data.get("ratings", [])
        avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else "—"
        csv_lines.append(f"{user_id},{name},{phone},{joined},{reminder},{avg_rating}")

    csv_content = "\n".join(csv_lines)
    file_path = "data/users_export.csv"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(csv_content)

    await message.answer_document(FSInputFile(file_path), caption=f"📊 Экспорт {len(users)} пользователей")


# ─── Фича 7: Оценка качества ───────────────────────────────────────────────
@dp.message(Command("rate"))
async def cmd_rate(message: types.Message):
    await message.answer(
        "⭐ Оцените качество обслуживания:\n"
        "Нажмите на кнопку ниже или введите число от 1 до 5.",
        reply_markup=rating_kb()
    )


@dp.callback_query(F.data.startswith("rate:"))
async def process_rating(callback: types.CallbackQuery):
    rating = int(callback.data.split(":")[1])
    user_id = str(callback.from_user.id)

    await update_user_field(user_id, "ratings", lambda x: x)  # placeholder
    users = await load_users()
    if user_id in users:
        if "ratings" not in users[user_id]:
            users[user_id]["ratings"] = []
        users[user_id]["ratings"].append(rating)
        await save_users(users)

    emojis = {1: "😞", 2: "😕", 3: "😐", 4: "😊", 5: "🤩"}
    await callback.message.edit_text(
        f"{emojis.get(rating, '⭐')} Спасибо за оценку: {rating}/5!"
    )
    await callback.answer("Оценка сохранена!")


# ═════════════════════════════════════════════════════════════════════════════
# ─── Обработчики заказов ────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

# ─── Фича 9: Повторный заказ ────────────────────────────────────────────────
@dp.message(F.text == "🔄 Повторить заказ")
async def repeat_order(message: types.Message):
    if str(message.from_user.id) == str(ADMIN_ID):
        await message.answer("⛔ Администратор не может оформлять заказы.")
        return
    user_id = str(message.from_user.id)
    users = await load_users()
    user_data = users.get(user_id, {})

    if not user_data.get("phone"):
        await message.answer(
            "⚠️ У вас нет сохранённых данных для повторного заказа.\n"
            "Оформите заказ обычным способом — и в следующий раз сможете повторить."
        )
        return

    preview_text = None
    repeat_lead_id = None
    if dispatcher_inbound_ready():
        try:
            disp = fetch_customer_order_status(
                normalize_phone(user_data.get("phone") or "") or None,
                telegram_user_id=user_id,
                group_id=DISPATCHER_GROUP_ID or None,
            )
            if disp.get("found"):
                preview_text = format_customer_order_status_message(disp)
                repeat_lead_id = disp.get("leadId")
        except Exception as e:
            logger.error("CRM repeat preview failed: %s", e)

    if not preview_text:
        last_order = get_last_order(user_id)
        if not last_order:
            await message.answer("⚠️ Не удалось найти ваш последний заказ.")
            return
        preview_text = last_order["text"]

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Подтвердить")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )
    await message.answer(
        "🔄 <b>Повторить последний заказ?</b>\n\n"
        f"{preview_text}\n\n"
        "Нажмите «✅ Подтвердить» или «❌ Отмена».",
        reply_markup=kb,
    )
    state_data = await dp.storage.get_data(chat_id=message.chat.id, user_id=message.from_user.id)
    state_data["repeat_order"] = True
    if repeat_lead_id:
        state_data["repeat_lead_id"] = str(repeat_lead_id)
    else:
        state_data.pop("repeat_lead_id", None)
    await dp.storage.set_data(chat_id=message.chat.id, user_id=message.from_user.id, data=state_data)


@dp.message(F.text == "✅ Подтвердить")
async def confirm_repeat_order(message: types.Message):
    state_data = await dp.storage.get_data(chat_id=message.chat.id, user_id=message.from_user.id)
    if not state_data.get("repeat_order"):
        return

    user_id = str(message.from_user.id)
    users = await load_users()
    user_data = users.get(user_id, {})

    name = display_contact_name_for_order(message, user_data)
    phone = user_data.get("phone", "—")
    address = (user_data.get("last_address") or "").strip() or "—"
    comment = "Повторный заказ"
    category = "Повторный заказ"

    lead_id = state_data.get("repeat_lead_id")
    if lead_id and dispatcher_inbound_ready():
        try:
            disp = fetch_customer_order_status(
                normalize_phone(user_data.get("phone") or "") or None,
                telegram_user_id=user_id,
                group_id=DISPATCHER_GROUP_ID or None,
            )
            entry = find_history_entry(disp, str(lead_id))
            if entry:
                title = str(entry.get("title") or "Заказ").strip() or "Заказ"
                category = f"Повтор: {title[:48]}"
                address = str(entry.get("address") or "").strip() or address
                comment = f"Повтор заказа «{title}»"
                desc = str(entry.get("description") or "").strip()
                if desc:
                    comment = f"{comment}. {desc[:300]}"
                entry_phone = str(entry.get("phone") or "").strip()
                if entry_phone:
                    phone = entry_phone
        except Exception as e:
            logger.error("CRM repeat confirm failed: %s", e)
    else:
        last_order = get_last_order(user_id)
        if last_order:
            comm_match = re.search(r"💬 Комментарий: (.+)", last_order["text"])
            if comm_match and comm_match.group(1) != "—":
                comment = comm_match.group(1) + " (повтор)"
            if address == "—":
                addr_match = re.search(r"📍 Адрес: (.+)", last_order["text"])
                if addr_match:
                    address = addr_match.group(1).strip()

    await finalize_repeat_order(
        message,
        name=name,
        phone=phone,
        address=address,
        comment=comment,
        category=category,
        user_data=user_data,
    )


# ─── Фича 8: Категории услуг + обычный заказ ───────────────────────────────
@dp.message(F.text == "🧾 Сделать заказ")
async def start_order(message: types.Message, state: FSMContext):
    if str(message.from_user.id) == str(ADMIN_ID):
        await message.answer("⛔ Администратор не может оформлять заказы.")
        return

    # Проверяем рабочее время
    await check_work_hours(message)

    await state.set_state(OrderForm.category)
    await message.answer(
        "Выберите тип услуги.\n"
        "<i>Данные из «⚙️ Настройки» подставляются сами. Дальше — 2 шага: комментарий и фото (фото можно пропустить).</i>",
        reply_markup=category_kb(),
    )


@dp.message(OrderForm.category)
async def process_category(message: types.Message, state: FSMContext):
    if message.text not in SERVICE_CATEGORIES:
        await message.answer("Пожалуйста, выберите категорию из списка:")
        return

    await state.update_data(category=message.text)
    user_id = str(message.from_user.id)
    users = await load_users()
    saved_phone = ((users.get(user_id, {}) or {}).get("phone") or "").strip()
    if saved_phone:
        await state.update_data(phone=saved_phone)
        await prompt_comment_after_phone(message, state, user_id)
    else:
        await state.set_state(OrderForm.phone)
        await prompt_phone_step(message, user_id)


@dp.message(OrderForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()

    # Если "Да" — используем сохранённый
    if phone.lower() in ("да", "yes", "ok"):
        users = await load_users()
        user_id = str(message.from_user.id)
        phone = users.get(user_id, {}).get("phone", "")
        if not phone:
            await message.answer("У вас нет сохранённого телефона. Введите номер:")
            return
        await state.update_data(phone=phone)
        await prompt_comment_after_phone(message, state, user_id)
        return

    if not phone_is_valid(phone):
        await message.answer(
            "Некорректный номер. Введите телефон ещё раз:\n"
            "<i>(нужно 10-15 цифр)</i>"
        )
        return

    normalized = normalize_phone(phone)
    await state.update_data(phone=normalized)

    # Сохраняем телефон в профиле (Фича 1)
    user_id = str(message.from_user.id)
    await update_user_field(user_id, "phone", normalized)

    await prompt_comment_after_phone(message, state, user_id)


@dp.message(OrderForm.comment)
async def process_comment(message: types.Message, state: FSMContext):
    comment = (message.text or "").strip()
    if comment == "⏭️ Без комментария" or comment.lower() in ("пропустить", "нет", "-", "без комментария"):
        comment = "—"

    await state.update_data(comment=comment)
    await state.set_state(OrderForm.photo)
    await message.answer(
        "📸 <b>Шаг 2 из 2</b> — фото объекта\n"
        "Пришлите снимок или нажмите «⏭️ Без фото».",
        reply_markup=photo_step_kb(),
    )


# ─── Фича 4: Фото к заказу ──────────────────────────────────────────────────
@dp.message(OrderForm.photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    """Сохраняем file_id фото в данные заказа."""
    photo = message.photo[-1]  # лучшее качество
    await state.update_data(photo_file_id=photo.file_id)
    await finalize_order(message, state)


@dp.message(OrderForm.photo)
async def skip_photo(message: types.Message, state: FSMContext):
    t = (message.text or "").strip().lower()
    if (message.text or "").strip() == "⏭️ Без фото" or t in _SKIP_PHOTO_TEXT:
        await state.update_data(photo_file_id=None)
        await finalize_order(message, state)
        return
    await message.answer(
        "Пришлите <b>фото</b> или нажмите «⏭️ Без фото».\n"
        "Произвольный текст не принимаем — чтобы заказ не ушёл случайно.",
        reply_markup=photo_step_kb(),
    )


async def finalize_order(message: types.Message, state: FSMContext):
    """Финальная обработка заказа."""
    data = await state.get_data()

    category = SERVICE_CATEGORIES.get(data.get("category", ""), "Общее")
    user_id = str(message.from_user.id)
    users = await load_users()
    prof = users.get(user_id, {}) or {}
    name = display_contact_name_for_order(message, prof)
    address = (prof.get("last_address") or "").strip() or "—"
    phone = data.get("phone", "—")
    comment = data.get("comment", "—")
    photo_file_id = data.get("photo_file_id")

    summary = (
        f"📦 <b>Новый заказ</b> | {category}\n"
        f"👤 Имя: {name}\n"
        f"📱 Телефон: {phone}\n"
        f"📍 Адрес: {address}\n"
        f"💬 Комментарий: {comment}\n"
        f"🆔 Клиент: {message.from_user.full_name} (id: <code>{message.from_user.id}</code>)"
    )

    # Уведомляем администратора
    if ADMIN_ID is not None:
        try:
            if photo_file_id:
                await bot.send_photo(ADMIN_ID, photo_file_id, caption=summary)
            else:
                await bot.send_message(ADMIN_ID, summary)
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить админа: {e}")
    else:
        logger.warning("⚠️ ADMIN_ID не задан")

    # Логируем заказ
    async with aiofiles.open(ORDER_LOG, "a", encoding="utf-8") as f:
        await f.write(summary + "\n\n")

    disp = send_order_to_dispatcher(
        category=category,
        name=name,
        phone=phone,
        address=address,
        comment=comment,
        telegram_user_id=str(message.from_user.id),
        telegram_full_name=message.from_user.full_name or name,
    )
    task: dict = {}
    yougile_err: Exception | None = None
    try:
        task = create_task(title=f"Заказ: {category} — {name}", description=summary)
    except Exception as e:
        logger.exception("❌ Ошибка при создании задачи в YouGile")
        yougile_err = e

    await _notify_admin_dispatcher_result(
        disp,
        context=f"📦 Новый заказ ({category})\n👤 {name}, {phone}",
    )

    if task.get("id"):
        await update_user_field(user_id, "last_order_id", task.get("id", "—"))

    lines = ["✅ Спасибо! Ваш заказ принят."]
    if disp.get("ok") and dispatcher_inbound_record_id(disp):
        if disp.get("leadId"):
            lines.append(f"📥 Диспетчер задач (заявка): <code>{disp['leadId']}</code>")
        else:
            lines.append(f"📋 Диспетчер задач: <code>{disp['taskId']}</code>")
        _dg = disp.get("groupId")
        if _dg:
            lines.append(f"📂 Группа в Диспетчере (id): <code>{_dg}</code> — откройте вкладку «Заявки» в этой группе.")
    elif not disp.get("skipped"):
        lines.append("⚠️ Диспетчер: заявка не создана (проверьте DISPATCHER_* на сервере бота и API).")
    if task.get("id"):
        lines.append(f"📋 YouGile: <code>{task['id']}</code>")
        lines.append(f"📝 Название: {task.get('title', '—')}")
    elif yougile_err:
        lines.append(f"⚠️ YouGile: {yougile_err}")
    if not disp.get("ok") and not task.get("id") and not disp.get("skipped"):
        lines = [
            "⚠️ Заказ принят, но не записан в диспетчер и не в YouGile.",
            f"YouGile: {yougile_err}" if yougile_err else "",
            "Менеджер свяжется с вами.",
        ]
        lines = [x for x in lines if x]

    response_text = "\n".join(lines)

    user_data = users.get(user_id, {})
    await message.answer(response_text, reply_markup=await main_menu_kb_with_admin(user_id, user_data))
    await state.clear()


@dp.message(F.text == "❌ Отмена", StateFilter("*"))
async def cancel_order(message: types.Message, state: FSMContext):
    await state.clear()
    await dp.storage.clear(chat_id=message.chat.id, user_id=message.from_user.id)
    users = await load_users()
    user_data = users.get(str(message.from_user.id), {})
    await message.answer("Оформление заказа отменено.", reply_markup=await main_menu_kb_with_admin(str(message.from_user.id), user_data))


# ─── Кнопки главного меню ──────────────────────────────────────────────────
@dp.message(Command("cabinet"))
async def cmd_cabinet(message: types.Message):
    user_id = str(message.from_user.id)
    users = await load_users()
    await show_client_cabinet(message, user_id, users.get(user_id, {}))


@dp.message(F.text == "🏠 Кабинет")
async def btn_cabinet(message: types.Message):
    user_id = str(message.from_user.id)
    users = await load_users()
    await show_client_cabinet(message, user_id, users.get(user_id, {}))


@dp.message(F.text == "👤 Мой профиль")
async def btn_profile(message: types.Message):
    await cmd_profile(message)


@dp.message(F.text == "⚙️ Настройки")
async def btn_settings(message: types.Message):
    await answer_settings_panel(message)


async def answer_settings_panel(message: types.Message) -> None:
    """Текст и клавиатура «Мои настройки» (общая для кнопки и callback)."""
    user_id = str(message.from_user.id)
    users = await load_users()
    user_data = users.get(user_id, {})

    name = user_data.get("full_name", "—")
    phone = user_data.get("phone", "—")
    address = user_data.get("last_address", "—")

    text = (
        f"⚙️ <b>Мои настройки</b>\n\n"
        f"👤 Имя: <b>{name}</b>\n"
        f"📱 Телефон: <b>{phone}</b>\n"
        f"📍 Адрес: <b>{address}</b>\n\n"
        f"Имя, телефон и адрес подставляются в заказ автоматически.\n"
        f"Выберите, что хотите изменить:"
    )
    await message.answer(text, reply_markup=settings_kb())


@dp.callback_query(F.data == "order_open_settings")
async def cb_order_open_settings(callback: types.CallbackQuery):
    """Из блока «нет адреса» — сразу открыть настройки."""
    await callback.answer()
    uid = str(callback.from_user.id)
    users = await load_users()
    await answer_settings_panel(callback.message)
    await callback.message.answer(
        "После сохранения адреса снова нажмите «🧾 Сделать заказ».",
        reply_markup=await main_menu_kb_with_admin(uid, users.get(uid, {}) or {}),
    )


# ─── Отслеживание блокировки бота ──────────────────────────────────────────
@dp.my_chat_member()
async def track_chat_member(event: types.ChatMemberUpdated, bot: Bot):
    """Отслеживает, когда пользователь блокирует/разблокирует бота."""
    user_id = str(event.from_user.id)
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    if old_status != "member" and new_status == "member":
        # Пользователь разблокировал бота
        logger.info(f"🔓 Пользователь {user_id} разблокировал бота")
    elif old_status == "member" and new_status in ("kicked", "left", "restricted"):
        # Пользователь заблокировал бота или удалил чат
        logger.warning(f"🚫 Пользователь {user_id} заблокировал бота ({new_status})")
        
        users = await load_users()
        if user_id in users and isinstance(users[user_id], dict):
            name = users[user_id].get("full_name", "—")
            phone = users[user_id].get("phone", "—")
            users[user_id]["blocked"] = True
            await save_users(users)
            
            # Уведомляем админа
            if ADMIN_ID:
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"🚫 <b>Пользователь заблокировал бота</b>\n\n"
                        f"👤 {name} ({user_id})\n"
                        f"📱 {phone}"
                    )
                except Exception:
                    pass


# ─── Админ: Удалить пользователя ───────────────────────────────────────────
@dp.message(Command("delete_user"))
async def cmd_delete_user(message: types.Message):
    """Удаляет пользователя из базы."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer(
            "📋 Использование: /delete_user <ID_пользователя>\n\n"
            "Пример: /delete_user 7599242480"
        )
        return

    user_id = args[1].strip()
    users = await load_users()

    if user_id not in users:
        await message.answer(f"❌ Пользователь {user_id} не найден.")
        return

    name = users[user_id].get("full_name", "—")
    del users[user_id]
    await save_users(users)

    await message.answer(f"✅ Пользователь {name} ({user_id}) удалён.")


# ─── Админ: Список заблокированных ─────────────────────────────────────────
@dp.message(Command("blocked"))
async def cmd_blocked(message: types.Message):
    """Показывает пользователей, заблокировавших бота."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return

    users = await load_users()
    blocked = [(uid, data) for uid, data in users.items()
               if isinstance(data, dict) and data.get("blocked")]

    if not blocked:
        await message.answer("✅ Заблокированных пользователей нет.")
        return

    text = f"🚫 Заблокированные ({len(blocked)}):\n\n"
    for uid, data in blocked:
        name = data.get("full_name", "—")
        phone = data.get("phone", "—")
        text += f"• {name} | {phone} | ID: <code>{uid}</code>\n"

    await message.answer(text)


@dp.callback_query(F.data == "settings_edit_name")
async def cb_settings_name(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("✏️ Введите новое имя:")
    await state.set_state(ProfileSettingsForm.editing_name)


@dp.callback_query(F.data == "settings_edit_phone")
async def cb_settings_phone(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("📱 Введите новый телефон:\n<i>(формат: +375XXXXXXXXX)</i>")
    await state.set_state(ProfileSettingsForm.editing_phone)


@dp.callback_query(F.data == "settings_edit_address")
async def cb_settings_address(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("📍 Введите новый адрес:")
    await state.set_state(ProfileSettingsForm.editing_address)


@dp.callback_query(F.data == "cabinet_status")
async def cb_cabinet_status(callback: types.CallbackQuery):
    await callback.answer()
    user_id = str(callback.from_user.id)
    users = await load_users()
    await send_order_status(callback.message, user_id, users.get(user_id, {}))


@dp.callback_query(F.data == "cabinet_orders")
async def cb_cabinet_orders(callback: types.CallbackQuery):
    await callback.answer()
    await my_orders(callback.message)


@dp.callback_query(F.data == "cabinet_new_order")
async def cb_cabinet_new_order(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_order(callback.message, state)


@dp.callback_query(F.data == "cabinet_settings")
async def cb_cabinet_settings(callback: types.CallbackQuery):
    await callback.answer()
    await answer_settings_panel(callback.message)


@dp.callback_query(F.data.startswith("repeat_lead:"))
async def cb_repeat_lead(callback: types.CallbackQuery):
    await callback.answer()
    if str(callback.from_user.id) == str(ADMIN_ID):
        await callback.message.answer("⛔ Администратор не может оформлять заказы.")
        return
    lead_id = callback.data.split(":", 1)[1]
    user_id = str(callback.from_user.id)
    users = await load_users()
    user_data = users.get(user_id, {})
    if not user_data.get("phone"):
        await callback.message.answer("⚠️ Сначала укажите телефон в настройках.")
        return
    if not dispatcher_inbound_ready():
        await callback.message.answer("⚠️ Повтор из истории доступен только с CRM диспетчера.")
        return
    try:
        disp = fetch_customer_order_status(
            normalize_phone(user_data.get("phone") or "") or None,
            telegram_user_id=user_id,
            group_id=DISPATCHER_GROUP_ID or None,
        )
    except Exception as e:
        logger.error("repeat_lead lookup failed: %s", e)
        await callback.message.answer("⚠️ Не удалось загрузить заявку.")
        return
    entry = find_history_entry(disp, lead_id)
    if not entry:
        await callback.message.answer("⚠️ Заявка не найдена.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"repeat_lead_confirm:{lead_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="repeat_lead_cancel")],
        ]
    )
    await callback.message.answer(
        f"🔄 <b>Повторить этот заказ?</b>\n\n{format_lead_status_block(entry)}",
        reply_markup=kb,
    )


@dp.callback_query(F.data.startswith("repeat_lead_confirm:"))
async def cb_repeat_lead_confirm(callback: types.CallbackQuery):
    lead_id = callback.data.split(":", 1)[1]
    user_id = str(callback.from_user.id)
    users = await load_users()
    user_data = users.get(user_id, {})
    if not user_data.get("phone"):
        await callback.answer("Укажите телефон в настройках", show_alert=True)
        return
    try:
        disp = fetch_customer_order_status(
            normalize_phone(user_data.get("phone") or "") or None,
            telegram_user_id=user_id,
            group_id=DISPATCHER_GROUP_ID or None,
        )
        entry = find_history_entry(disp, lead_id)
    except Exception:
        entry = None
    if not entry:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    title = str(entry.get("title") or "Заказ").strip() or "Заказ"
    name = display_contact_name_for_order(callback.message, user_data)
    phone = str(entry.get("phone") or user_data.get("phone") or "—")
    address = str(entry.get("address") or "").strip() or (user_data.get("last_address") or "").strip() or "—"
    comment = f"Повтор заказа «{title}»"
    desc = str(entry.get("description") or "").strip()
    if desc:
        comment = f"{comment}. {desc[:300]}"
    await finalize_repeat_order(
        callback.message,
        name=name,
        phone=phone,
        address=address,
        comment=comment,
        category=f"Повтор: {title[:48]}",
        user_data=user_data,
    )
    await callback.answer("Заказ принят")


@dp.callback_query(F.data == "repeat_lead_cancel")
async def cb_repeat_lead_cancel(callback: types.CallbackQuery):
    await callback.message.edit_text("Повтор заказа отменён.")
    await callback.answer()


@dp.callback_query(F.data == "settings_back")
async def cb_settings_back(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("⚙️ Настройки отменены.")
    user_id = str(callback.from_user.id)
    await callback.message.answer("⚙️ Главное меню:", reply_markup=await main_menu_kb_with_admin(user_id))


# ─── Обработка ввода настроек ──────────────────────────────────────────────
@dp.message(ProfileSettingsForm.editing_name)
async def process_edit_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Введите заново:")
        return

    user_id = str(message.from_user.id)
    await update_user_field(user_id, "full_name", name)

    await state.clear()
    users = await load_users()
    user_data = users.get(user_id, {})
    user_data["_user_id"] = user_id
    await message.answer(
        f"✅ Имя изменено на: <b>{name}</b>",
        reply_markup=await main_menu_kb_with_admin(user_id, user_data)
    )


@dp.message(ProfileSettingsForm.editing_phone)
async def process_edit_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not phone_is_valid(phone):
        await message.answer("Некорректный номер. Введите ещё раз:\n<i>(нужно 10-15 цифр)</i>")
        return

    normalized = normalize_phone(phone)
    user_id = str(message.from_user.id)
    await update_user_field(user_id, "phone", normalized)

    await state.clear()
    users = await load_users()
    user_data = users.get(user_id, {})
    user_data["_user_id"] = user_id
    await message.answer(
        f"✅ Телефон изменён на: <b>{normalized}</b>",
        reply_markup=await main_menu_kb_with_admin(user_id, user_data)
    )


@dp.message(ProfileSettingsForm.editing_address)
async def process_edit_address(message: types.Message, state: FSMContext):
    address = message.text.strip()
    if not address:
        await message.answer("Адрес не может быть пустым. Введите заново:")
        return

    user_id = str(message.from_user.id)
    await update_user_field(user_id, "last_address", address)

    await state.clear()
    users = await load_users()
    user_data = users.get(user_id, {})
    user_data["_user_id"] = user_id
    await message.answer(
        f"✅ Адрес изменён на: <b>{address}</b>",
        reply_markup=await main_menu_kb_with_admin(user_id, user_data)
    )


@dp.message(F.text == "🛡️ Админ-панель")
async def btn_admin_panel(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("🛡️ <b>Админ-панель</b>\nВыберите действие:", reply_markup=admin_panel_kb())


@dp.message(F.text == "🔙 Назад")
async def btn_back(message: types.Message):
    users = await load_users()
    user_data = users.get(str(message.from_user.id), {})
    user_data["_user_id"] = str(message.from_user.id)
    await message.answer("📋 Главное меню:", reply_markup=await main_menu_kb_with_admin(str(message.from_user.id), user_data))


@dp.message(F.text == "👥 Пользователи")
async def btn_users(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return
    await list_users(message)


@dp.message(F.text == "📊 Статистика")
async def btn_stats(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return
    await cmd_stats(message)


@dp.message(F.text == "🔧 ТО статус")
async def btn_maintenance(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return
    await cmd_maintenance(message)


@dp.message(F.text == "📦 Заказы")
async def btn_pending_orders(message: types.Message):
    """Показывает все невыполненные заказы."""
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return

    try:
        async with aiofiles.open(ORDER_LOG, "r", encoding="utf-8") as f:
            log_content = await f.read()
    except Exception:
        await message.answer("⚠️ Не удалось загрузить историю заказов.")
        return

    completed = await load_completed_orders()
    orders = parse_orders_from_log(log_content)
    pending = [o for o in orders if o["id"] not in completed]

    if not pending:
        await message.answer("✅ Все заказы выполнены!")
        return

    keyboard = []
    for order in pending[:20]:  # Показываем максимум 20
        keyboard.append([InlineKeyboardButton(
            text=f"📦 #{order['id']} {order['name']} ({order['category']})",
            callback_data=f"order_view:{order['id']}"
        )])

    await message.answer(
        f"📦 <b>Невыполненные заказы</b> ({len(pending)}):\n"
        f"Нажмите на заказ для просмотра и отметки выполнения.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@dp.callback_query(F.data.startswith("order_view:"))
async def cb_order_view(callback: types.CallbackQuery):
    """Показывает детали заказа и кнопку выполнения."""
    order_id = int(callback.data.split(":")[1])

    try:
        async with aiofiles.open(ORDER_LOG, "r", encoding="utf-8") as f:
            log_content = await f.read()
    except Exception:
        await callback.answer("Ошибка загрузки!", show_alert=True)
        return

    orders = parse_orders_from_log(log_content)
    order = next((o for o in orders if o["id"] == order_id), None)
    if not order:
        await callback.answer("Заказ не найден!", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выполнен", callback_data=f"order_done:{order_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="orders_list")],
    ])

    text = (
        f"📦 <b>Заказ #{order['id']}</b>\n\n"
        f"Категория: {order['category']}\n"
        f"Клиент: {order['name']}\n"
        f"Телефон: {order['phone']}\n"
        f"Адрес: {order['address']}\n\n"
        f"ID клиента: <code>{order['user_id']}</code>"
    )

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "orders_list")
async def cb_orders_list(callback: types.CallbackQuery):
    """Возврат к списку заказов."""
    await callback.message.delete()
    await btn_pending_orders(callback.message)
    await callback.answer()


@dp.callback_query(F.data.startswith("order_done:"))
async def cb_order_done(callback: types.CallbackQuery):
    """Отмечает заказ как выполненный."""
    order_id = int(callback.data.split(":")[1])

    completed = await load_completed_orders()
    completed.add(order_id)
    await save_completed_orders(completed)

    try:
        async with aiofiles.open(ORDER_LOG, "r", encoding="utf-8") as f:
            log_content = await f.read()
    except Exception:
        await callback.answer("Ошибка!", show_alert=True)
        return

    orders = parse_orders_from_log(log_content)
    order = next((o for o in orders if o["id"] == order_id), None)
    name = order["name"] if order else "—"

    # Обновляем сообщение
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="orders_list")],
    ])
    await callback.message.edit_text(
        f"✅ <b>Заказ #{order_id} выполнен!</b>\n\n"
        f"Клиент: {name}",
        reply_markup=kb
    )
    await callback.answer("Заказ отмечен как выполненный!")


@dp.message(F.text == "📢 Рассылка")
async def btn_broadcast(message: types.Message, state: FSMContext):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return
    await message.answer(
        "📢 <b>Режим рассылки</b>\n"
        "Отправьте сообщение, которое нужно разослать всем пользователям.\n"
        "Для отмены введите /cancel или нажмите «🔙 Назад».",
        reply_markup=admin_panel_kb()
    )
    await state.set_state(BroadcastForm.message)


@dp.message(F.text == "📥 Экспорт CSV")
async def btn_export(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ.")
        return
    await cmd_export(message)


# ─── Фича: Мои заказы (история) ─────────────────────────────────────────────
@dp.message(F.text == "📋 Мои заказы")
async def my_orders(message: types.Message):
    user_id = str(message.from_user.id)
    users = await load_users()
    user_data = users.get(user_id, {})
    menu_kb = await main_menu_kb_with_admin(user_id, user_data)
    phone = normalize_phone((user_data.get("phone") or "").strip()) if user_data.get("phone") else ""

    if dispatcher_inbound_ready():
        try:
            disp = fetch_customer_order_status(
                phone or None,
                telegram_user_id=user_id,
                group_id=DISPATCHER_GROUP_ID or None,
            )
        except Exception as e:
            logger.error("Dispatcher orders history failed: %s", e)
            disp = {"ok": False, "found": False}
        messages = format_customer_order_history_items(disp, limit=5)
        if messages:
            for item in messages:
                lead_id = item.get("lead_id")
                if lead_id:
                    row_kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="🔄 Повторить",
                                    callback_data=f"repeat_lead:{lead_id}",
                                )
                            ]
                        ]
                    )
                    await message.answer(item["text"], reply_markup=row_kb)
                else:
                    await message.answer(item["text"])
            await message.answer("👇 Меню", reply_markup=menu_kb)
            return

    # Ищем в локальном логе
    try:
        async with aiofiles.open(ORDER_LOG, "r", encoding="utf-8") as f:
            log_content = await f.read()
    except Exception:
        await message.answer("⚠️ Не удалось загрузить историю заказов.", reply_markup=menu_kb)
        return

    # Извлекаем заказы пользователя
    pattern = rf"((?:📦 <b>Новый заказ</b>|🔄 <b>).*?id: <code>{user_id}</code>\))"
    matches = re.findall(pattern, log_content, re.DOTALL)

    if not matches:
        await message.answer(
            "📭 У вас пока нет заказов.\nНажмите «🧾 Сделать заказ», чтобы оформить.",
            reply_markup=menu_kb,
        )
        return

    # Показываем последние 3
    last_orders = matches[-3:]
    for i, order in enumerate(reversed(last_orders)):
        clean = order.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
        header = f"📋 <b>Заказ #{len(matches) - i}</b>" if i < 2 else f"📋 <b>Последний заказ</b>"
        is_last = i == len(last_orders) - 1
        await message.answer(
            f"{header}\n\n{clean}",
            reply_markup=menu_kb if is_last else None,
        )


# ─── Обработка любых сообщений в FSM (подсказка) ────────────────────────────
@dp.message(StateFilter(OrderForm))
async def handle_unexpected_in_form(message: types.Message):
    await message.answer(
        "Пожалуйста, следуйте инструкциям бота.\n"
        "Для отмены нажмите «❌ Отмена»."
    )


# ═════════════════════════════════════════════════════════════════════════════
# ─── Админ: список пользователей ────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

@dp.message(Command("users"))
async def list_users(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ может просматривать список.")
        return

    users = await load_users()
    if not users:
        await message.answer("👥 Пока никто не подключился к боту.")
        return

    def get_joined(data):
        if isinstance(data, dict):
            return data.get("joined", "1970-01-01T00:00:00")
        return data

    sorted_users = sorted(users.items(), key=lambda x: get_joined(x[1]))
    PAGE_SIZE = 50
    pages = [sorted_users[i:i + PAGE_SIZE] for i in range(0, len(sorted_users), PAGE_SIZE)]

    for page_idx, page_users in enumerate(pages):
        text = f"👥 Всего пользователей: <b>{len(users)}</b>"
        if len(pages) > 1:
            text += f" (стр. {page_idx + 1}/{len(pages)})"
        text += "\n\n"

        for uid, data in page_users:
            if str(uid) == str(ADMIN_ID):
                continue
            if isinstance(data, dict):
                username = data.get("username")
                full_name = data.get("full_name")
                phone = data.get("phone", "—")
                address = data.get("last_address", "—")
                joined = data.get("joined", "—")
                ratings = data.get("ratings", [])
                blocked = data.get("blocked", False)
                avg_rating = f"{sum(ratings)/len(ratings):.1f}⭐" if ratings else "—"

                if username:
                    name_display = f"@{username}"
                elif full_name:
                    name_display = full_name
                else:
                    name_display = "❓"
            else:
                name_display = "❓"
                phone = "—"
                address = "—"
                joined = str(data)
                avg_rating = "—"
                blocked = False

            status_icon = "🚫" if blocked else "•"
            text += f"{status_icon} <b>{name_display}</b>\n"
            text += f"  ID: <code>{uid}</code> | 📱 {phone}\n"
            text += f"  📍 Адрес: {address}\n"
            text += f"  ⭐ {avg_rating} | 📅 {joined}\n\n"

        await message.answer(text)


# ═════════════════════════════════════════════════════════════════════════════
# ─── Цикл напоминаний ───────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

def calc_next_maintenance(joined_str: str, last_maintenance_str: str = None) -> datetime | None:
    """Вычисляет следующую дату ТО."""
    if last_maintenance_str:
        try:
            last_maint = datetime.fromisoformat(last_maintenance_str)
            return last_maint + timedelta(days=MAINTENANCE_INTERVAL_MONTHS * 30)
        except (ValueError, TypeError):
            pass
    if not joined_str:
        return None
    try:
        joined_at = datetime.fromisoformat(joined_str)
        return joined_at + timedelta(days=MAINTENANCE_INTERVAL_MONTHS * 30)
    except (ValueError, TypeError):
        return None


async def handle_send_error(error, user_id):
    """Обрабатывает ошибки отправки и помечает пользователя заблокированным."""
    text = str(error).lower()
    if any(blocked_word in text for blocked_word in ["blocked", "chat not found", "user is deactivated"]):
        users = await load_users()
        if user_id in users and isinstance(users[user_id], dict):
            if not users[user_id].get("blocked"):
                users[user_id]["blocked"] = True
                await save_users(users)
                logger.warning(f"🚫 Авто-блокировка: {user_id}")
                if ADMIN_ID:
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            f"🚫 <b>Авто-блокировка</b>\n"
                            f"Пользователь {user_id} помечен как заблокированный.\n"
                            f"Причина: {error}"
                        )
                    except Exception:
                        pass
        return True
    return False


async def send_maintenance_reminder(user_id: str, user_data: dict, next_maint: datetime):
    """Отправляет напоминание пользователю."""
    days_left = (next_maint - datetime.now()).days
    if days_left <= 0:
        text = (
            "🔧 <b>Напоминание о ТО</b>\n\n"
            "Прошло 6 месяцев с момента последнего обслуживания. "
            "Рекомендуем провести техническое обслуживание скважины, "
            "чтобы всё работало как часы.\n\n"
            "Нажмите 🧾 Сделать заказ, чтобы записаться."
        )
    else:
        text = (
            "📅 <b>Плановое ТО</b>\n\n"
            f"Через {days_left} дн. ({next_maint.strftime('%d.%m.%Y')}) рекомендуется провести ТО скважины.\n\n"
            "Нажмите 🧾 Сделать заказ, чтобы записаться заранее."
        )
    try:
        await bot.send_message(int(user_id), text, reply_markup=maintenance_reminder_kb())
        return True
    except Exception as e:
        await handle_send_error(e, user_id)
        return False


async def notify_admin_maintenance(admin_id: int, user_id: str, user_data: dict, next_maint: datetime, status: str):
    """Уведомляет админа о статусе ТО пользователя."""
    name = user_data.get("full_name", "—")
    phone = user_data.get("phone", "—")
    days_left = (next_maint - datetime.now()).days

    text = (
        f"🔧 <b>ТО пользователя</b>\n\n"
        f"👤 {name} ({user_id})\n"
        f"📱 {phone}\n"
        f"📆 Дата ТО: {next_maint.strftime('%d.%m.%Y')}\n"
        f"📌 Статус: {status}\n"
        f"⏰ Осталось: {days_left} дн."
    )
    try:
        await bot.send_message(admin_id, text)
        return True
    except Exception as e:
        logger.warning(f"Не удалось уведомить админа о ТО {user_id}: {e}")
        return False


async def reminder_loop():
    """Проверка напоминаний о ТО каждый час.
    
    Логика:
    - За 7 дней до ТО → напоминание пользователю + уведомление админу
    - В день ТО (0 дней) → напоминание пользователю + уведомление админу
    - После ТО (просрочено) → напоминание пользователю + уведомление админу
    - После напоминания → сброс через 30 дней (следующий цикл)
    """
    while True:
        try:
            now = datetime.now()
            users = await load_users()
            changed = False
            admin_notifications = []

            for user_id, user_data in list(users.items()):
                if not isinstance(user_data, dict):
                    continue

                # Пропускаем самого админа
                if str(user_id) == str(ADMIN_ID):
                    continue

                joined_str = user_data.get("joined")
                if not joined_str:
                    continue

                # Дата последнего напоминания или None
                last_reminder = user_data.get("last_reminder_sent")
                next_maint = calc_next_maintenance(joined_str, last_reminder)
                if not next_maint:
                    continue

                days_until = (next_maint - now).days
                last_reminder_date = user_data.get("last_reminder_sent")

                # Проверяем, не отправляли ли напоминание в последние 30 дней
                should_remind = False
                status_text = ""

                if last_reminder_date:
                    try:
                        last_dt = datetime.fromisoformat(last_reminder_date)
                        days_since_reminder = (now - last_dt).days
                        if days_since_reminder < 30:
                            continue  # Не беспокоим слишком часто
                    except (ValueError, TypeError):
                        pass

                if days_until <= -30:
                    # Просрочено более чем на 30 дней — повторяем напоминание
                    should_remind = True
                    status_text = "🔴 ТО просрочено"
                elif days_until <= 0:
                    # День ТО или просрочено
                    should_remind = True
                    status_text = f"🔴 ТО сегодня/просрочено ({abs(days_until)} дн.)"
                elif days_until <= 7:
                    # За неделю до ТО
                    should_remind = True
                    status_text = f"🟡 ТО через {days_until} дн."

                if should_remind:
                    # Отправляем пользователю
                    user_sent = await send_maintenance_reminder(user_id, user_data, next_maint)
                    
                    # Формируем уведомление админу
                    if user_sent:
                        users[user_id]["last_reminder_sent"] = now.isoformat()
                        changed = True
                        admin_notifications.append(
                            (user_id, user_data, next_maint, status_text)
                        )
                        logger.info(f"✅ Напоминание о ТО → {user_id} ({status_text})")
                    else:
                        # Проверка на блокировку
                        try:
                            await bot.send_message(int(ADMIN_ID), f"Test msg to {user_id}")
                        except Exception as e:
                            await handle_send_error(e, user_id)

            # Уведомляем админа списком
            if admin_notifications:
                report = f"🔧 <b>Напоминания о ТО</b> ({len(admin_notifications)}):\n\n"
                for uid, udata, maint, status in admin_notifications:
                    name = udata.get("full_name", "—")
                    phone = udata.get("phone", "—")
                    report += f"• {name} | {phone} | {status} | {maint.strftime('%d.%m.%Y')}\n"
                
                await bot.send_message(int(ADMIN_ID), report)
                logger.info(f"📋 Отчёт админу о ТО: {len(admin_notifications)} уведомлений")

            if changed:
                await save_users(users)

        except Exception as e:
            logger.error(f"❌ Ошибка в цикле напоминаний: {e}")

        await asyncio.sleep(3600)  # Проверка каждый час


# ═════════════════════════════════════════════════════════════════════════════
# ─── FastAPI вебхук ─────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🌐 FastAPI сервер запущен")
    yield
    logger.info("🌐 FastAPI сервер остановлен")


app = FastAPI(lifespan=lifespan)


@app.post("/yougile/webhook")
async def yougile_webhook(request: Request):
    """Принимает вебхуки от YouGile с проверкой секрета."""
    if YOUGILE_WEBHOOK_SECRET:
        secret_header = request.headers.get("X-Yougile-Secret")
        if not secret_header:
            raise HTTPException(status_code=401, detail="Missing secret header")
        if secret_header != YOUGILE_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid secret")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if ADMIN_ID is not None:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🔔 Событие из YouGile:\n<pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre>"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить событие: {e}")

    return {"status": "ok"}


@app.post("/dispatcher/leads-alert")
async def dispatcher_leads_alert(request: Request):
    """Вебхук от API диспетчера: напоминания по «висящим» заявкам → админу в Telegram."""
    if DISPATCHER_INBOUND_API_KEY:
        auth = request.headers.get("Authorization") or ""
        if not auth.startswith("Bearer ") or auth[7:].strip() != DISPATCHER_INBOUND_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    text = str(data.get("text") or "").strip()
    if ADMIN_ID is not None and text:
        try:
            await bot.send_message(ADMIN_ID, text)
        except Exception as e:
            logger.error("Не удалось отправить leads-alert админу: %s", e)
    return {"ok": True}


def _phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _telegram_user_id_by_phone(users: dict, phone: str) -> str | None:
    digits = _phone_digits(phone)
    if not digits or len(digits) < 6:
        return None
    for uid, data in users.items():
        if _phone_digits(str((data or {}).get("phone") or "")) == digits:
            return str(uid)
    return None


@app.post("/dispatcher/customer-notify")
async def dispatcher_customer_notify(request: Request):
    """Вебхук от API диспетчера: уведомление клиенту о стадии заявки."""
    if DISPATCHER_INBOUND_API_KEY:
        auth = request.headers.get("Authorization") or ""
        if not auth.startswith("Bearer ") or auth[7:].strip() != DISPATCHER_INBOUND_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    text = str(data.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "empty_text"}
    tg_raw = str(data.get("telegramUserId") or data.get("telegram_user_id") or "").strip()
    phone = str(data.get("phone") or "").strip()
    target_id = tg_raw if tg_raw.isdigit() else None
    if not target_id and phone:
        users = await load_users()
        target_id = _telegram_user_id_by_phone(users, phone)
    if not target_id:
        logger.info("customer-notify: получатель не найден (phone=%s tg=%s)", phone[:6] if phone else "", tg_raw[:6] if tg_raw else "")
        return {"ok": True, "delivered": False, "reason": "recipient_not_found"}
    try:
        await bot.send_message(int(target_id), text, reply_markup=client_cabinet_inline_kb())
        return {"ok": True, "delivered": True}
    except Exception as e:
        logger.error("customer-notify: не удалось отправить %s: %s", target_id, e)
        return {"ok": False, "delivered": False, "error": str(e)}


@app.get("/health")
async def health_check():
    """Эндпоинт для проверки работоспособности."""
    return {"status": "ok"}


# ═════════════════════════════════════════════════════════════════════════════
# ─── Graceful Shutdown ─────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

async def graceful_shutdown():
    """Корректная остановка бота."""
    logger.info("🛑 Получен сигнал остановки...")

    try:
        users = await load_users()
        await save_users(users)
        logger.info("✅ Данные пользователей сохранены")
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении данных: {e}")

    try:
        await bot.session.close()
        logger.info("✅ Сессия бота закрыта")
    except Exception as e:
        logger.error(f"❌ Ошибка при закрытии сессии: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# ─── Главная точка входа ───────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

async def main():
    logger.info("✅ Бот запускается: Telegram + FastAPI + 9 новых фич")
    check_startup()

    await migrate_old_format()

    try:
        users = await load_users()
        stats = await asyncio.to_thread(
            sync_missing_maintenance_dispatcher_cards,
            users,
            calc_next_maintenance,
        )
        if stats.get("ran") and stats.get("created", 0) > 0:
            await save_users(users)
            logger.info(
                "Диспетчер ТО: создано карточек=%s ошибок=%s",
                stats.get("created"),
                stats.get("failed"),
            )
        elif stats.get("ran") and stats.get("failed", 0) > 0:
            logger.warning(
                "Диспетчер ТО-синхрон: создано=%s ошибок=%s (users.json не менялся)",
                stats.get("created"),
                stats.get("failed"),
            )
    except Exception as e:
        logger.exception("Диспетчер ТО-синхрон при старте: %s", e)

    # Обработчики сигналов (только Unix)
    loop = asyncio.get_event_loop()
    if os.name != "nt":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(graceful_shutdown()))

    reminder_task = asyncio.create_task(reminder_loop())

    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)

    try:
        await asyncio.gather(
            dp.start_polling(bot),
            server.serve(),
        )
    except asyncio.CancelledError:
        logger.info("⚠️ Получен сигнал отмены")
    finally:
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        logger.info("👋 Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
