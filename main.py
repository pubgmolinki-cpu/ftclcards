import asyncio, psycopg2, os, html, random, time
from datetime import datetime, timedelta
import pytz 
from psycopg2.extras import DictCursor
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859)) # Твой ID

CHANNELS = ["@ftclcardschannel", "@waxteamiftl", "@ftcloff"]
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Словари состояний
cooldowns, penalty_cooldowns, guess_cooldowns, pvp_cooldowns = {}, {}, {}, {}
active_matches, waiting_for_bet = {}, {}

# --- ФУНКЦИЯ ЛЕНИВОЙ НАСТРОЙКИ БД ---
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    # Создаем колонку is_banned, если её нет
    cur.execute("""
        DO $$ 
        BEGIN 
            BEGIN
                ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE;
            EXCEPTION
                WHEN duplicate_column THEN RAISE NOTICE 'column is_banned already exists';
            END;
        END $$;
    """)
    conn.commit()
    cur.close()
    conn.close()

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# --- ЛОГИ И АНТИЧИТ ---
async def send_log(text):
    try:
        await bot.send_message(ADMIN_ID, f"📑 <b>LOG:</b>\n{text}")
    except: pass

async def check_user_status(user_id):
    """Проверка на бан"""
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT is_banned FROM users WHERE user_id = %s", (user_id,))
    res = cur.fetchone()
    cur.close(); conn.close()
    return res[0] if res else False

# --- МИНИ-ИГРА ПЕНАЛЬТИ (ФИКС БАГА + АНТИЧИТ) ---
@dp.callback_query(F.data == "game_penalty")
async def penalty_init(callback: types.CallbackQuery):
    if await check_user_status(callback.from_user.id):
        return await callback.answer("🚫 Доступ заблокирован античитом.", show_alert=True)
    waiting_for_bet[callback.from_user.id] = "penalty"
    await callback.message.edit_text("💰 Введите ставку на пенальти (от 1,000 ⭐):")

async def run_penalty(message: types.Message, bet: int):
    user_id = message.from_user.id
    
    # Античит: проверка на дурака (отрицательные ставки или гигантские суммы)
    if bet <= 0 or bet > 1000000:
        await send_log(f"🚨 <b>ПОПЫТКА ВЗЛОМА!</b>\nЮзер: @{message.from_user.username}\nСтавка: {bet}\n<b>ДЕЙСТВИЕ:</b> Игнор.")
        return await message.answer("❌ Невалидная ставка.")

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    u = cur.fetchone()

    # ЖЕСТКИЙ ФИКС: Проверка баланса ДО начала игры
    if not u or u['balance'] < bet:
        cur.close(); conn.close()
        return await message.answer(f"❌ Недостаточно ⭐! Твой баланс: {u['balance'] if u else 0}")

    cur.close(); conn.close()
    
    kb = InlineKeyboardBuilder()
    for s in ["Л", "Ц", "П"]: kb.button(text=s, callback_data=f"pnl_{bet}")
    await message.answer(f"⚽ Ставка {bet} ⭐ принята. Куда бьешь?", reply_markup=kb.adjust(3).as_markup())

@dp.callback_query(F.data.startswith("pnl_"))
async def penalty_finish(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    bet = int(callback.data.split("_")[1])
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    u = cur.fetchone()

    # Повторная проверка прямо в момент удара (защита от мульти-кликов)
    if not u or u['balance'] < bet:
        conn.close()
        return await callback.message.edit_text("❌ Ошибка баланса!")

    if random.choice([True, False]): # 50/50
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, user_id))
        res = f"⚽ <b>ГОЛ!</b> +{bet} ⭐"
        await send_log(f"💰 @{callback.from_user.username} +{bet} (Пенальти)")
    else:
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, user_id))
        res = f"🧤 <b>Мимо!</b> -{bet} ⭐"
        await send_log(f"📉 @{callback.from_user.username} -{bet} (Пенальти)")

    conn.commit(); cur.close(); conn.close()
    await callback.message.edit_text(res)

# --- НОВАЯ СИСТЕМА МАТЧ (PvP) ---
@dp.message(Command("match"))
async def pvp_start(message: types.Message, command: CommandObject):
    if message.chat.type == "private": return
    if not command.args or not command.args.isdigit(): return await message.answer("❌ `/match 1000`")
    
    bet = int(command.args)
    if bet < 100: return
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    if not u or u['balance'] < bet: return await message.answer("❌ Мало ⭐")
    cur.close(); conn.close()

    m_id = f"m_{message.message_id}"
    active_matches[m_id] = {
        "p1": message.from_user.id, "p1_name": message.from_user.full_name,
        "p2": None, "p2_name": None, "bet": bet, "p1_ready": False, "p2_ready": False,
        "p1_pts": random.randint(180, 290), "p2_pts": random.randint(180, 290)
    }
    kb = InlineKeyboardBuilder().button(text=f"Принять ({bet} ⭐)", callback_data=f"pj_{m_id}")
    await message.answer(f"🏟 <b>МАТЧ:</b> {message.from_user.mention_html()} на <b>{bet} ⭐</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pj_"))
async def pvp_join(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]
    match = active_matches.get(m_id)
    if not match or match['p2']: return
    if callback.from_user.id == match['p1']: return await callback.answer("Нельзя с собой!")

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (callback.from_user.id,))
    u = cur.fetchone()
    if not u or u['balance'] < match['bet']: return await callback.answer("Нет звезд!", show_alert=True)
    
    # Списание сразу!
    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id IN (%s, %s)", (match['bet'], match['p1'], callback.from_user.id))
    conn.commit(); cur.close(); conn.close()

    match['p2'], match['p2_name'] = callback.from_user.id, callback.from_user.full_name
    
    for pid, pts in [(match['p1'], match['p1_pts']), (match['p2'], match['p2_pts'])]:
        try: await bot.send_message(pid, f"🎫 Твой состав: <b>{pts} ПТС</b>")
        except: pass

    kb = InlineKeyboardBuilder().button(text="Играть ✅", callback_data=f"pg_{m_id}")
    await callback.message.edit_text(f"⚔️ <b>Оппонент найден!</b>\n{match['p1_name']} vs {match['p2_name']}\n📩 ПТС в личке!", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pg_"))
async def pvp_go(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]
    match = active_matches.get(m_id)
    if not match: return
    
    if callback.from_user.id == match['p1']: match['p1_ready'] = True
    if callback.from_user.id == match['p2']: match['p2_ready'] = True
    
    if match['p1_ready'] and match['p2_ready']:
        await callback.message.edit_text("⚽ <b>МАТЧ ИДЕТ...</b>")
        await asyncio.sleep(3)
        
        p1, p2, bank = match['p1_pts'], match['p2_pts'], match['bet']*2
        conn = get_db_connection(); cur = conn.cursor()
        if p1 > p2:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bank, match['p1']))
            res = f"🏆 <b>{match['p1_name']}</b> победил!"
        elif p2 > p1:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bank, match['p2']))
            res = f"🏆 <b>{match['p2_name']}</b> победил!"
        else:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id IN (%s,%s)", (match['bet'], match['p1'], match['p2']))
            res = "🤝 Ничья!"
        
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(f"🏁 <b>ИТОГ:</b>\n{match['p1_name']}: {p1}\n{match['p2_name']}: {p2}\n\n{res}")
        active_matches.pop(m_id, None)

# --- АДМИН-КОМАНДЫ ---
@dp.message(Command("ban"))
async def ban_user(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    if not command.args: return
    uid = int(command.args)
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET is_banned = TRUE WHERE user_id = %s", (uid,))
    conn.commit(); cur.close(); conn.close()
    await message.answer(f"🚫 Юзер {uid} забанен.")

# --- ОБЩИЙ ОБРАБОТЧИК СТАВОК ---
@dp.message(lambda m: m.from_user.id in waiting_for_bet)
async def handle_bets(message: types.Message):
    state = waiting_for_bet.pop(message.from_user.id)
    if not message.text.isdigit(): return
    val = int(message.text)
    if state == "penalty": await run_penalty(message, val)

# --- ЗАПУСК ---
async def main():
    init_db() # Само создаст колонку при запуске
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
