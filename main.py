import asyncio
import psycopg2
import os
import random
import time
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from psycopg2.extras import DictCursor

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859)) # Твой ID
CHANNELS = ["@ftclcardschannel", "@waxteamiftl", "@ftcloff"] # Обязательные каналы

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Глобальные состояния (кулдауны и матчи)
cooldowns = {}
active_matches = {}

# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 5000
        );
        CREATE TABLE IF NOT EXISTS user_cards (
            id SERIAL PRIMARY KEY, user_id BIGINT, card_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS active_teams (
            user_id BIGINT PRIMARY KEY, gk_id INTEGER, def_ids INTEGER[], mid_ids INTEGER[], fwd_ids INTEGER[]
        );
    """)
    conn.commit(); cur.close(); conn.close()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def check_sub(uid):
    """Проверка подписки на 3 канала"""
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch, uid)
            if m.status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

async def send_admin_log(text):
    """Отправка лога в личку админу"""
    try:
        await bot.send_message(ADMIN_ID, f"📑 <b>ADMIN LOG</b>\n{text}")
    except: pass

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid, uname = message.from_user.id, message.from_user.username
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (uid, uname))
    conn.commit(); cur.close(); conn.close()
    
    await send_admin_log(f"Новый пользователь: @{uname} ({uid})")
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>Добро пожаловать в FTCL Cards!</b>\nСобери команду мечты прямо сейчас.", 
                         reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

# --- ПОШАГОВЫЙ ПАК-ОПЕНИНГ ---
@dp.message(F.text == "Получить Карту 🏆")
async def get_card_logic(message: types.Message):
    uid = message.from_user.id
    if not await check_sub(uid):
        return await message.answer("❌ <b>Ошибка!</b>\nДля открытия паков подпишись на каналы:\n" + "\n".join(CHANNELS))

    now = time.time()
    if uid in cooldowns and now - cooldowns[uid] < 14400:
        rem = int(14400 - (now - cooldowns[uid]))
        return await message.answer(f"⏳ <b>Кулдаун!</b>\nСледующий пак через: {rem//3600}ч. {(rem%3600)//60}мин.")

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
    card = cur.fetchone()
    if not card: return await message.answer("⚠️ Карты временно закончились.")

    # Красивая анимация
    status = await message.answer("Открываем пак... 💼")
    await asyncio.sleep(2)
    await status.edit_text(f"Позиция: <b>{card['position']}</b>")
    await asyncio.sleep(2)
    await status.edit_text(f"Позиция: <b>{card['position']}</b>\nКлуб: <b>{card['club']}</b>")
    await asyncio.sleep(2)
    await status.edit_text(f"Позиция: <b>{card['position']}</b>\nКлуб: <b>{card['club']}</b>\nРейтинг: <b>{card['rating']}</b>")
    await asyncio.sleep(1)
    await status.delete()

    # Сохранение
    cooldowns[uid] = now
    cur.execute("UPDATE users SET balance = balance + 1250 WHERE user_id = %s", (uid,))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
    conn.commit(); cur.close(); conn.close()

    await send_admin_log(f"🎫 Пак открыт: @{message.from_user.username}\nВыпал: {card['name']} ({card['rating']})")
    
    caption = f"🎉 <b>НОВАЯ КАРТА!</b>\n\n👤 <b>{card['name'].upper()}</b>\n📊 Рейтинг: <b>{card['rating']}</b>\n🛡 Клуб: <b>{card['club']}</b>\n💰 Бонус: <b>+1,250 ⭐</b>"
    await message.answer_photo(card['photo_id'], caption=caption)

# --- ПРОФИЛЬ И КОЛЛЕКЦИЯ ---
@dp.message(F.text == "Профиль 👤")
async def show_profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = %s", (message.from_user.id,))
    cnt = cur.fetchone()[0]
    
    kb = InlineKeyboardBuilder()
    kb.button(text="💼 Моя Коллекция", callback_data="view_coll")
    kb.button(text="🛡 Моя Команда", callback_data="view_team")
    
    await message.answer(f"👤 <b>Профиль:</b> @{message.from_user.username}\n💰 Баланс: <b>{u['balance']:,}</b> ⭐\n🗂 Всего карт: <b>{cnt}</b>", 
                         reply_markup=kb.adjust(1).as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data == "view_coll")
async def coll_callback(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT c.name, c.rating FROM user_cards uc JOIN all_cards c ON uc.card_id = c.id WHERE uc.user_id = %s ORDER BY c.rating DESC LIMIT 15", (callback.from_user.id,))
    cards = cur.fetchall()
    if not cards: return await callback.answer("У вас нет карт!", show_alert=True)
    text = "💼 <b>Топ-15 твоих карт:</b>\n\n" + "\n".join([f"• {c[0]} ({c[1]})" for c in cards])
    await callback.message.answer(text); await callback.answer()

# --- PvP СИСТЕМА ---
@dp.message(Command("match"))
async def cmd_match(message: types.Message, command: CommandObject):
    if not command.args or not command.args.isdigit(): 
        return await message.answer("Введите ставку: <code>/match 1000</code>")
    bet = int(command.args)
    m_id = f"{message.from_user.id}_{int(time.time())}"
    active_matches[m_id] = {"p1": message.from_user.id, "p1_n": message.from_user.full_name, "bet": bet, "round": 1, "score": [0,0]}
    
    await send_admin_log(f"⚔️ Матч создан: {message.from_user.full_name} на {bet} ⭐")
    
    kb = InlineKeyboardBuilder().button(text=f"Принять ({bet} ⭐)", callback_data=f"join_{m_id}")
    await message.answer(f"🏟 <b>{message.from_user.full_name}</b> вызывает на матч!\n💰 Ставка: <b>{bet}</b> ⭐", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("join_"))
async def join_callback(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    if not m or m['p2'] or callback.from_user.id == m['p1']: return
    
    m['p2'] = callback.from_user.id; m['p2_n'] = callback.from_user.full_name
    kb = InlineKeyboardBuilder().button(text="🤜 Атаковать!", callback_data=f"kick_{m_id}")
    await callback.message.edit_text(f"⚽️ <b>Матч начался!</b>\n{m['p1_n']} 🆚 {m['p2_n']}", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("kick_"))
async def kick_callback(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    if not m: return await callback.answer("Матч завершен.")
    
    goal = random.choice([True, False])
    if goal:
        if m['round'] % 2 != 0: m['score'][0] += 1
        else: m['score'][1] += 1
    
    m['round'] += 1
    if m['round'] > 5:
        res = f"🏁 <b>ИТОГ: {m['score'][0]}:{m['score'][1]}</b>\n"
        win = m['p1_n'] if m['score'][0] > m['score'][1] else (m['p2_n'] if m['score'][1] > m['score'][0] else "Ничья")
        await callback.message.edit_text(res + f"Победитель: <b>{win}</b>")
        active_matches.pop(m_id, None)
    else:
        kb = InlineKeyboardBuilder().button(text="🤜 След. удар", callback_data=f"kick_{m_id}")
        await callback.message.edit_text(f"🥅 Раунд {m['round']-1}/5\nСчёт: <b>{m['score'][0]}:{m['score'][1]}</b>\n{'✅ ГОЛ!' if goal else '❌ СЕЙВ!'}", reply_markup=kb.as_markup())
    await callback.answer()

# --- ПРОЧЕЕ ---
@dp.message(F.text == "Рефералка 👥")
async def cmd_ref(message: types.Message):
    bot_info = await bot.get_me()
    await message.answer(f"👥 <b>Реферальная система</b>\nСсылка: <code>t.me/{bot_info.username}?start={message.from_user.id}</code>")

@dp.message(F.text == "ТОП-10 📊")
async def cmd_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    top = cur.fetchall()
    txt = "🏆 <b>ТОП-10 ИГРОКОВ:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} — {r[1]:,} ⭐" for i, r in enumerate(top)])
    await message.answer(txt); cur.close(); conn.close()

# --- ЗАПУСК ---
async def main():
    init_db()
    logger.info("Бот запущен и логирование активно!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
