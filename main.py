import asyncio
import logging
import re
import json
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from config import API_TOKEN, ADMIN_ID
from tools.yougile_api import create_task
from fastapi import FastAPI, Request
import uvicorn

logging.basicConfig(level=logging.INFO)

os.makedirs("data", exist_ok=True)
USER_FILE = "data/users.json"
ORDER_LOG = "data/orders.log"

if not os.path.exists(USER_FILE):
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)

if not os.path.exists(ORDER_LOG):
    with open(ORDER_LOG, "w", encoding="utf-8") as f:
        f.write("")

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

class OrderForm(StatesGroup):
    name = State()
    phone = State()
    address = State()
    comment = State()

def main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🧾 Сделать заказ")]],
        resize_keyboard=True
    )

def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

def phone_is_valid(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    return 10 <= len(digits) <= 14

def load_users():
    if os.path.exists(USER_FILE):
        with open(USER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

user_joined = load_users()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in user_joined:
        user_joined[user_id] = {
            "joined": datetime.now().isoformat(),
            "username": message.from_user.username
        }
        save_users(user_joined)
    await message.answer(
        "Привет! Я приму ваш заказ и передам менеджеру.\n"
        "Нажмите «🧾 Сделать заказ», чтобы оформить.",
        reply_markup=main_menu_kb()
    )

@dp.message(Command("users"))
async def list_users(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("⛔ Только админ может просматривать список.")
        return

    users = load_users()
    if not users:
        await message.answer("👥 Пока никто не подключился к боту.")
        return

    def get_joined(data):
        if isinstance(data, dict):
            return data.get("joined", "1970-01-01T00:00:00")
        return data  # старый формат (строка)

    sorted_users = sorted(users.items(), key=lambda x: get_joined(x[1]))
    text = f"👥 Всего пользователей: <b>{len(users)}</b>\n\n"

    for uid, data in sorted_users:
        if isinstance(data, dict):
            name = data.get("username", "❓ Неизвестно")
            joined = data.get("joined", "—")
        else:
            name = "❓ Старый формат"
            joined = data
        text += f"• <b>{name}</b>\n  ID: <code>{uid}</code>\n  Дата: {joined}\n\n"

    await message.answer(text)

@dp.message(F.text == "🧾 Сделать заказ")
async def start_order(message: types.Message, state: FSMContext):
    await state.set_state(OrderForm.name)
    await message.answer("Введите ваше имя:", reply_markup=cancel_kb())

@dp.message(F.text == "❌ Отмена", StateFilter("*"))
async def cancel_order(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Оформление заказа отменено.", reply_markup=main_menu_kb())

@dp.message(OrderForm.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(OrderForm.phone)
    await message.answer("Введите ваш телефон:", reply_markup=cancel_kb())

@dp.message(OrderForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not phone_is_valid(phone):
        await message.answer("Некорректный номер. Введите ещё раз:")
        return
    await state.update_data(phone=phone)
    await state.set_state(OrderForm.address)
    await message.answer("Введите адрес объекта:", reply_markup=cancel_kb())

@dp.message(OrderForm.address)
async def process_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text.strip())
    await state.set_state(OrderForm.comment)
    await message.answer("Напишите комментарий к заказу:", reply_markup=cancel_kb())

@dp.message(OrderForm.comment)
async def process_comment(message: types.Message, state: FSMContext):
    await state.update_data(comment=message.text.strip())
    data = await state.get_data()

    summary = (
        "📦 <b>Новый заказ</b>\n"
        f"👤 Имя: {data['name']}\n"
        f"📱 Телефон: {data['phone']}\n"
        f"📍 Адрес: {data['address']}\n"
        f"💬 Комментарий: {data['comment']}\n"
        f"🆔 Клиент: {message.from_user.full_name} (id: {message.from_user.id})"
    )

    await bot.send_message(ADMIN_ID, summary)

    with open(ORDER_LOG, "a", encoding="utf-8") as f:
        f.write(summary + "\n\n")

    try:
        task = create_task(
            title=f"Заказ от {data['name']}",
            description=summary
        )
        await message.answer(
            f"✅ Спасибо! Ваш заказ принят и добавлен в YouGile.\n"
            f"ID: {task.get('id')}\n"
            f"Название: {task.get('title')}",
            reply_markup=main_menu_kb()
        )
    except Exception as e:
        await message.answer(
            f"⚠️ Заказ принят, но не удалось создать задачу в YouGile.\nОшибка: {e}",
            reply_markup=main_menu_kb()
        )

    await state.clear()

async def reminder_loop():
    while True:
        now = datetime.now()
        for user_id, user_data in list(user_joined.items()):
            # Старый формат (строка)
            if isinstance(user_data, str):
                user_data = {"joined": user_data, "username": None}
                user_joined[user_id] = user_data
                save_users(user_joined)

            # Неполный словарь (нет joined)
            if isinstance(user_data, dict) and "joined" not in user_data:
                user_data["joined"] = datetime.now().isoformat()
                save_users(user_joined)

            joined_at = datetime.fromisoformat(user_data["joined"])
            if now - joined_at >= timedelta(days=180):
                await bot.send_message(
                    int(user_id),
                    "🔧 🔔 Уже 6 месяцев с момента последнего обслуживания. "
                    "Чтобы всё работало как часы, рекомендуем записаться на проверку."
                )
                user_data["joined"] = now.isoformat()
                save_users(user_joined)
        await asyncio.sleep(10)

app = FastAPI()

@app.post("/yougile/webhook")
async def yougile_webhook(request: Request):
    data = await request.json()
    await bot.send_message(ADMIN_ID, f"Новое событие из YouGile:\n{data}")
    return {"status": "ok"}

async def main():
    asyncio.create_task(reminder_loop())

    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()
    )

if __name__ == "__main__":
    asyncio.run(main())
