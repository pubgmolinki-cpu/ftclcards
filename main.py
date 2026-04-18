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
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859))
CHANNELS = ["@ftclcardschannel", "@waxteamiftl", "@ftcloff"]
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Глобальные состояния
cooldowns, pvp_cooldowns, guess_cooldowns = {}, {}, {}
active_matches, waiting_for_bet = {}, {}

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    conn = psycopg2.connect(DATABASE_URL); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 5000,
            is_banned BOOLEAN DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS active_teams (
            user_id BIGINT PRIMARY KEY,
            gk_id INTEGER, def_ids INTEGER[], mid_ids INTEGER[], fwd_ids INTEGER[]
        );
        DO $$ BEGIN 
            ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE;
        EXCEPTION WHEN duplicate_column THEN NULL; END $$;
    """)
    conn.commit(); cur.close(); conn.close()

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# --- ЛОГИКА АНТИЧИТА ---
async def send_log(text):
    try: await bot.send_message(ADMIN_ID, f"📑 <b>LOG:</b>\n{text}")
    except: pass

async def is_banned(uid):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT is_banned FROM users WHERE user_id = %s", (uid,))
    res = cur.fetchone()
    cur.close(); conn.close()
    return res[0] if res else False

# --- СИСТЕМА СОСТАВА (4-3-3) ---
def auto_collect_team(user_id):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("""
            SELECT c.id, c.name, c.rating, c.position 
            FROM user_cards uc 
            JOIN all_cards c ON uc.card_id = c.id 
            WHERE uc.user_id = %s
        """, (user_id,))
        cards = cur.fetchall()
        if len(cards) < 11: return False, "Нужно минимум 11 карт!"

        pos_map = {"Вратарь": [], "Защитник": [], "Полузащитник": [], "Нападающий": []}
        for c in cards:
            p = c['position']
            if p in pos_map: pos_map[p].append(c)

        if len(pos_map["Вратарь"]) < 1 or len(pos_map["Защитник"]) < 4 or len(pos_map["Полузащитник"]) < 3 or len(pos_map["Нападающий"]) < 3:
            return False, "Не хватает игроков для 4-3-3 (нужно: 1 Вратарь, 4 Защ, 3 ПЗ, 3 Нап)!"

        gk = sorted(pos_map["Вратарь"], key=lambda x: x['rating'], reverse=True)[0]
        defs = sorted(pos_map["Защитник"], key=lambda x: x['rating'], reverse=True)[:4]
        mids = sorted(pos_map["Полузащитник"], key=lambda x: x['rating'], reverse=True)[:3]
        fwds = sorted(pos_map["Нападающий"], key=lambda x: x['rating'], reverse=True)[:3]

        cur.execute("""
            INSERT INTO active_teams (user_id, gk_id, def_ids, mid_ids, fwd_ids)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET 
            gk_id=EXCLUDED.gk_id, def_ids=EXCLUDED.def_ids, mid_ids=EXCLUDED.mid_ids, fwd_ids=EXCLUDED.fwd_ids
        """, (user_id, gk['id'], [d['id'] for d in defs], [m['id'] for m in mids], [f['id'] for f in fwds]))
        conn.commit(); return True, "Состав 4-3-3 автоматически собран из лучших карт!"
    finally: cur.close(); conn.close()

# --- ХЕНДЛЕРЫ МЕНЮ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    uid = message.from_user.id
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (uid, message.from_user.username))
    conn.commit(); cur.close(); conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "Профиль 👤")
async def profile_menu(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    kb = InlineKeyboardBuilder()
    kb.button(text="🛡 Моя Команда", callback_data="my_team")
    kb.button(text="💼 Коллекция", callback_data="my_collection")
    await message.answer(f"👤 <b>Профиль</b>\n💰 Баланс: <b>{u['balance']}</b> ⭐", reply_markup=kb.adjust(1).as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data == "my_team")
async def show_team(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM active_teams WHERE user_id = %s", (callback.from_user.id,))
    t = cur.fetchone()
    
    if not t:
        text = "❌ Команда еще не собрана. Нажми 'Авто-Сбор'."
    else:
        all_ids = [t['gk_id']] + t['def_ids'] + t['mid_ids'] + t['fwd_ids']
        cur.execute("SELECT name, rating, position FROM all_cards WHERE id = ANY(%s)", (all_ids,))
        cards = cur.fetchall()
        text = "🛡 <b>Твой состав (4-3-3):</b>\n\n"
        for c in cards: text += f"• {c['position']}: <b>{c['name']}</b> ({c['rating']})\n"

    kb = InlineKeyboardBuilder().button(text="🔄 Авто-Сбор лучших", callback_data="auto_collect")
    await callback.message.edit_text(text, reply_markup=kb.as_markup()); cur.close(); conn.close()

@dp.callback_query(F.data == "auto_collect")
async def handle_collect(callback: types.CallbackQuery):
    ok, msg = auto_collect_team(callback.from_user.id)
    await callback.answer(msg, show_alert=True)
    if ok: await show_team(callback)

# --- МИНИ-ИГРЫ ---

@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🥅 Пенальти", callback_data="game_penalty")
    kb.button(text="🧩 Угадай Игрока", callback_data="game_guess")
    kb.button(text="⚔️ PvP Матч", callback_data="pvp_info")
    await message.answer("🎯 <b>Выберите игру:</b>", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data == "pvp_info")
async def pvp_info(callback: types.CallbackQuery):
    await callback.message.answer("⚔️ <b>PvP Матч (4-3-3)</b>\n\nВызови игрока в чате:\n<code>/match [ставка]</code>\n\n<i>Нужен собранный состав в Профиле!</i>")
    await callback.answer()

# --- ЛОГИКА PvP МАТЧА ---

@dp.message(Command("match"))
async def start_match_cmd(message: types.Message, command: CommandObject):
    uid = message.from_user.id
    if uid in pvp_cooldowns and time.time() - pvp_cooldowns[uid] < 1800:
        return await message.answer("⏳ Кулдаун 30 минут!")
    
    if not command.args or not command.args.isdigit(): return await message.answer("Юзай: /match 1000")
    bet = int(command.args)
    if bet <= 0: return await message.answer("❌ Ставка должна быть > 0")

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    cur.execute("SELECT 1 FROM active_teams WHERE user_id = %s", (uid,))
    if not cur.fetchone(): return await message.answer("❌ Сначала сделай Авто-Сбор в Профиле!")
    if u['balance'] < bet: return await message.answer("❌ Недостаточно ⭐")
    
    m_id = f"m_{uid}_{int(time.time())}"
    active_matches[m_id] = {"p1": uid, "p1_name": message.from_user.full_name, "p2": None, "bet": bet, "round": 1, "score": [0,0]}
    kb = InlineKeyboardBuilder().button(text=f"Принять ({bet} ⭐)", callback_data=f"join_{m_id}")
    await message.answer(f"🏟 <b>{message.from_user.full_name}</b> ищет матч!\n💰 Ставка: {bet}", reply_markup=kb.as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data.startswith("join_"))
async def match_join(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    uid = callback.from_user.id
    if not m or m['p2']: return await callback.answer("Матч уже начат.")
    if uid == m['p1']: return await callback.answer("Нельзя играть с собой!")
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    cur.execute("SELECT 1 FROM active_teams WHERE user_id = %s", (uid,))
    if not cur.fetchone(): return await callback.answer("Собери команду в профиле!", show_alert=True)
    if u['balance'] < m['bet']: return await callback.answer("Нет денег!")

    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id IN (%s, %s)", (m['bet'], m['p1'], uid))
    conn.commit(); cur.close(); conn.close()
    
    m['p2'] = uid; m['p2_name'] = callback.from_user.full_name
    pvp_cooldowns[m['p1']] = pvp_cooldowns[uid] = time.time()
    kb = InlineKeyboardBuilder().button(text="🤜 Атаковать!", callback_data=f"kick_{m_id}")
    await callback.message.edit_text(f"⚽️ <b>Матч начался!</b>\n{m['p1_name']} vs {m['p2_name']}", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("kick_"))
async def match_kick(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    if not m or callback.from_user.id not in [m['p1'], m['p2']]: return

    atk_id = m['p1'] if m['round'] % 2 != 0 else m['p2']
    def_id = m['p2'] if m['round'] % 2 != 0 else m['p1']
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT name, rating FROM all_cards WHERE id = ANY((SELECT fwd_ids FROM active_teams WHERE user_id = %s)) ORDER BY RANDOM() LIMIT 1", (atk_id,))
    atk_p = cur.fetchone()
    cur.execute("SELECT name, rating FROM all_cards WHERE id = ANY((SELECT def_ids FROM active_teams WHERE user_id = %s)) ORDER BY RANDOM() LIMIT 1", (def_id,))
    def_p = cur.fetchone()

    chance = 50 + (atk_p['rating'] - def_p['rating'])
    goal = random.randint(1, 100) <= chance
    if goal:
        if atk_id == m['p1']: m['score'][0] += 1
        else: m['score'][1] += 1
    
    icon = "🟢" if goal else "🔴"
    event = f"{icon} <b>{atk_p['name']}</b> атакует... {'ГОЛ!' if goal else 'МИМО!'}"
    m['round'] += 1
    
    if m['round'] > 5:
        win_id = m['p1'] if m['score'][0] > m['score'][1] else (m['p2'] if m['score'][1] > m['score'][0] else None)
        bank = m['bet'] * 2
        if win_id: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bank, win_id))
        else: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id IN (%s, %s)", (m['bet'], m['p1'], m['p2']))
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(f"🏁 <b>ИТОГ: {m['score'][0]}:{m['score'][1]}</b>\nПобедил: <b>{m['p1_name'] if win_id == m['p1'] else (m['p2_name'] if win_id else 'Ничья')}</b>")
        active_matches.pop(m_id, None)
    else:
        kb = InlineKeyboardBuilder().button(text="🤜 След. Момент", callback_data=f"kick_{m_id}")
        await callback.message.edit_text(f"Раунд {m['round']-1}/5\n{event}\n\n📊 Счёт {m['score'][0]}:{m['score'][1]}", reply_markup=kb.as_markup())
        cur.close(); conn.close()

# --- ОСТАЛЬНЫЕ МИНИ ИГРЫ ---

@dp.callback_query(F.data == "game_penalty")
async def penalty_init(callback: types.CallbackQuery):
    waiting_for_bet[callback.from_user.id] = "penalty"
    await callback.message.edit_text("💰 Введите ставку на Пенальти:")

async def run_penalty(message, bet):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    if cur.fetchone()['balance'] < bet: return await message.answer("❌ Мало ⭐")
    cur.close(); conn.close()
    kb = InlineKeyboardBuilder()
    for s in ["Л", "Ц", "П"]: kb.button(text=s, callback_data=f"pnl_{bet}")
    await message.answer(f"🥅 Ставка {bet}. Куда бьешь?", reply_markup=kb.adjust(3).as_markup())

@dp.callback_query(F.data.startswith("pnl_"))
async def penalty_finish(callback: types.CallbackQuery):
    bet = int(callback.data.split("_")[1]); uid = callback.from_user.id
    conn = get_db_connection(); cur = conn.cursor()
    goal = random.choice([True, False])
    if goal: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, uid))
    else: cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, uid))
    conn.commit(); cur.close(); conn.close()
    await callback.message.edit_text("⚽️ ГОЛ!" if goal else "🧤 МИМО!")

# --- СТАНДАРТНЫЕ КОМАНДЫ ---

@dp.message(F.text == "Рефералка 👥")
async def ref_sys(message: types.Message):
    await message.answer(f"👥 Ссылка: <code>t.me/{(await bot.get_me()).username}?start={message.from_user.id}</code>")

@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    top = cur.fetchall(); cur.close(); conn.close()
    await message.answer("📊 <b>ТОП-10:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} - {r[1]}⭐" for i, r in enumerate(top)]))

@dp.message(lambda m: m.from_user.id in waiting_for_bet)
async def handle_input(message: types.Message):
    state = waiting_for_bet.pop(message.from_user.id)
    if not message.text.isdigit(): return
    if state == "penalty": await run_penalty(message, int(message.text))

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
