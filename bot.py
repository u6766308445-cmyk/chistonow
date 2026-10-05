import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID") or 0)
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
ORDERS_FILE = Path(__file__).parent / "orders.jsonl"

ZONES = [
    "Петроградский район",
    "Крестовский остров",
    "Каменный остров",
    "Петровская коса",
]

# Цены должны совпадать со списком ITEMS в docs/index.html.
# Бот считает сумму сам и не доверяет цифрам из приложения.
PRICES = {
    "sofa2": ("Диван двухместный", 2500),
    "sofa3": ("Диван трёхместный", 3200),
    "corner": ("Угловой диван", 4500),
    "chair": ("Кресло", 1200),
    "pouf": ("Пуф", 600),
    "seat": ("Стул с мягким сиденьем", 400),
    "mattress": ("Матрас", 2200),
}

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()
awaiting_photos: dict[int, int] = {}  # id клиента -> номер заказа (сбрасывается при перезапуске)


def zone_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=z, callback_data=f"zone:{i}")]
        for i, z in enumerate(ZONES)
    ]
    rows.append([InlineKeyboardButton(text="Другой район", callback_data="zone:other")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def save_order(order: dict) -> int:
    number = 1
    if ORDERS_FILE.exists():
        with ORDERS_FILE.open(encoding="utf-8") as f:
            number = sum(1 for _ in f) + 1
    order["no"] = number
    with ORDERS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(order, ensure_ascii=False) + "\n")
    return number


def parse_order(raw: str) -> dict:
    data = json.loads(raw)
    zone = data["zone"]
    if zone not in ZONES:
        raise ValueError("zone")
    lines, total = [], 0
    for it in data["items"]:
        name, price = PRICES[it["id"]]
        qty = int(it["qty"])
        if not 1 <= qty <= 20:
            raise ValueError("qty")
        total += price * qty
        lines.append(f"• {name} × {qty}")
    if not lines:
        raise ValueError("items")
    return {
        "zone": zone,
        "items": lines,
        "total": total,
        "date": str(data["date"])[:10],
        "time": str(data["time"])[:20],
        "address": str(data["address"])[:200],
        "phone": str(data["phone"])[:30],
        "note": str(data.get("note", ""))[:500],
    }


@dp.message(CommandStart())
async def start(m: Message):
    await m.answer(
        "Здравствуйте! Мы чистим мягкую мебель у вас дома.\n"
        "Сначала проверим, выезжаем ли мы к вам. Где вы находитесь?",
        reply_markup=zone_keyboard(),
    )


@dp.callback_query(F.data.startswith("zone:"))
async def on_zone(c: CallbackQuery):
    await c.answer()
    value = c.data.split(":", 1)[1]
    if value == "other":
        await c.message.answer(
            "К сожалению, пока мы работаем только на Петроградской стороне, "
            "Крестовском и Каменном островах и Петровской косе. "
            "Если вы окажетесь в этих районах, напишите /start."
        )
        return
    zone = ZONES[int(value)]
    if not WEBAPP_URL:
        await c.message.answer("Приложение для заказа пока не подключено. Попробуйте позже.")
        return
    kb = ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[[
            KeyboardButton(
                text="Заказать химчистку",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}?zone={quote(zone)}"),
            )
        ]],
    )
    await c.message.answer(
        f"{zone} входит в нашу зону. Нажмите кнопку внизу, чтобы оформить заказ.",
        reply_markup=kb,
    )


@dp.message(F.web_app_data)
async def on_order(m: Message):
    try:
        order = parse_order(m.web_app_data.data)
    except (KeyError, ValueError, TypeError):
        await m.answer("Не удалось прочитать заказ. Попробуйте ещё раз: /start")
        return

    user = m.from_user
    order["user_id"] = user.id
    order["username"] = user.username or ""
    order["created"] = datetime.now().isoformat(timespec="seconds")
    number = save_order(order)
    awaiting_photos[user.id] = number

    if ADMIN_CHAT_ID:
        text = (
            f"Новый заказ №{number}\n"
            f"Район: {order['zone']}\n"
            f"Дата и время: {order['date']}, {order['time']}\n"
            f"Адрес: {order['address']}\n"
            f"Телефон: {order['phone']}\n"
            f"Клиент: {user.full_name}"
            + (f" (@{user.username})" if user.username else f" (id {user.id})")
            + "\n\n" + "\n".join(order["items"])
            + f"\n\nИтого от {order['total']} ₽"
            + (f"\nКомментарий: {order['note']}" if order["note"] else "")
        )
        try:
            await m.bot.send_message(ADMIN_CHAT_ID, text)
        except Exception:
            logging.exception("Не удалось отправить заказ №%s администратору", number)

    await m.answer(
        f"Заказ №{number} принят. Ориентировочная стоимость от {order['total']} ₽, "
        "точную назовёт мастер после осмотра.\n\n"
        "Пришлите, пожалуйста, фото мебели: так мастер заранее оценит загрязнения. "
        "Мы свяжемся с вами для подтверждения."
    )


@dp.message(F.photo)
async def on_photo(m: Message):
    number = awaiting_photos.get(m.from_user.id)
    if not number:
        await m.answer("Чтобы оформить заказ, нажмите /start")
        return
    if ADMIN_CHAT_ID:
        await m.bot.send_photo(
            ADMIN_CHAT_ID, m.photo[-1].file_id, caption=f"Фото к заказу №{number}"
        )
    await m.answer("Фото получено. Можете прислать ещё.")


@dp.message(Command("id"))
async def chat_id(m: Message):
    await m.answer(f"ID этого чата: {m.chat.id}")


async def main():
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN. Скопируйте .env.example в .env и заполните его.")
    if not ADMIN_CHAT_ID:
        logging.warning("ADMIN_CHAT_ID не задан: заказы будут только сохраняться в orders.jsonl")
    await dp.start_polling(Bot(BOT_TOKEN))


if __name__ == "__main__":
    asyncio.run(main())
