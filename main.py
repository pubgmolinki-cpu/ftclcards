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

async def send_log(text):
    try: await bot.send_message(ADMIN_ID, f"📑 <b>LOG:</b>\n{text}")
    except: pass

async def check_sub(uid):
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch, uid)
            if m.status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_stars_by_rating(rating):
    if rating >= 90: return 2500
    if rating >= 80: return 1500
    return 500

# --- СИСТЕМА КОМАНДЫ ---
def auto_collect_team(user_id):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT c.id, c.name, c.rating, c.position FROM user_cards uc JOIN all_cards c ON uc.card_id = c.id WHERE uc.user_id = %s", (user_id,))
        cards = cur.fetchall()
        if len(cards) < 11: return False, "❌ Нужно минимум 11 карт для состава!"
        pos_map = {"Вратарь": [], "Защитник": [], "Полузащитник": [], "Нападающий": []}
        for c in cards:
            if c['position'] in pos_map: pos_map[c['position']].append(c)
        if len(pos_map["Вратарь"]) < 1 or len(pos_map["Защитник"]) < 4 or len(pos_map["Полузащитник"]) < 3 or len(pos_map["Нападающий"]) < 3:
            return False, "❌ Не хватает игроков на позиции (1 GK, 4 DEF, 3 MID, 3 FWD)!"
        gk = sorted(pos_map["Вратарь"], key=lambda x: x['rating'], reverse=True)[0]
        defs = sorted(pos_map["Защитник"], key=lambda x: x['rating'], reverse=True)[:4]
        mids = sorted(pos_map["Полузащитник"], key=lambda x: x['rating'], reverse=True)[:3]
        fwds = sorted(pos_map["Нападающий"], key=lambda x: x['rating'], reverse=True)[:3]
        cur.execute("INSERT INTO active_teams (user_id, gk_id, def_ids, mid_ids, fwd_ids) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET gk_id=EXCLUDED.gk_id, def_ids=EXCLUDED.def_ids, mid_ids=EXCLUDED.mid_ids, fwd_ids=EXCLUDED.fwd_ids", (user_id, gk['id'], [d['id'] for d in defs], [m['id'] for m in mids], [f['id'] for f in fwds]))
        conn.commit(); return True, "✅ Состав 4-3-3 успешно собран!"
    finally: cur.close(); conn.close()

# --- ОСНОВНЫЕ ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (message.from_user.id, message.from_user.username))
    conn.commit(); cur.close(); conn.close()
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>\nСобери команду мечты и доминируй в матчах!", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "Профиль 👤")
async def profile_menu(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = %s", (message.from_user.id,))
    cnt = cur.fetchone()[0]
    kb = InlineKeyboardBuilder()
    kb.button(text="🛡 Моя Команда", callback_data="my_team")
    kb.button(text="💼 Моя Коллекция", callback_data="my_collection")
    await message.answer(f"👤 <b>Профиль игрока:</b> @{message.from_user.username}\n\n💰 Баланс: <b>{u['balance']}</b> ⭐\n🗂 Всего карт: <b>{cnt}</b>", reply_markup=kb.adjust(1).as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data == "my_collection")
async def show_collection(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT c.name, c.rating FROM user_cards uc JOIN all_cards c ON uc.card_id = c.id WHERE uc.user_id = %s ORDER BY c.rating DESC LIMIT 30", (callback.from_user.id,))
    cards = cur.fetchall()
    if not cards: return await callback.answer("❌ У вас еще нет карт!", show_alert=True)
    text = "💼 <b>Твои топ-30 карт:</b>\n\n" + "\n".join([f"• {c['name']} ({c['rating']})" for c in cards])
    await callback.message.answer(text); await callback.answer()
    cur.close(); conn.close()

@dp.callback_query(F.data == "my_team")
async def show_team(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM active_teams WHERE user_id = %s", (callback.from_user.id,))
    t = cur.fetchone()
    if not t: text = "❌ Команда не собрана. Нажми 'Авто-Сбор' ниже."
    else:
        ids = [t['gk_id']] + t['def_ids'] + t['mid_ids'] + t['fwd_ids']
        cur.execute("SELECT name, rating, position FROM all_cards WHERE id = ANY(%s)", (ids,))
        text = "🛡 <b>Твой активный состав (4-3-3):</b>\n\n" + "\n".join([f"• {c['position']}: <b>{c['name']}</b> ({c['rating']})" for c in cur.fetchall()])
    kb = InlineKeyboardBuilder().button(text="🔄 Авто-Сбор", callback_data="auto_collect")
    await callback.message.answer(text, reply_markup=kb.as_markup()); await callback.answer()
    cur.close(); conn.close()

@dp.callback_query(F.data == "auto_collect")
async def handle_collect(callback: types.CallbackQuery):
    ok, msg = auto_collect_team(callback.from_user.id)
    await callback.answer(msg, show_alert=True)

# --- ПОЛУЧЕНИЕ КАРТЫ ---
@dp.message(F.text == "Получить Карту 🏆")
async def give_card(message: types.Message):
    uid = message.from_user.id
    if not await check_sub(uid): return await message.answer("❌ Сначала подпишись на наши каналы в описании!")
    now = time.time()
    if uid in cooldowns and now - cooldowns[uid] < 14400:
        rem = int(14400 - (now - cooldowns[uid]))
        return await message.answer(f"⏳ Ты уже получал карту! Приходи через {rem//3600}ч. {(rem%3600)//60}мин.")
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
    card = cur.fetchone()
    if not card: return await message.answer("⚠️ Карты в базе закончились!")
    
    cooldowns[uid] = now
    reward = get_stars_by_rating(card['rating'])
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, uid))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
    conn.commit(); cur.close(); conn.close()
    
    await message.answer_photo(card['photo_id'], caption=f"🎉 <b>Тебе выпала карта!</b>\n\n👤 Имя: <b>{card['name']}</b>\n📊 Рейтинг: <b>{card['rating']}</b>\n🛡 Клуб: <b>{card['club']}</b>\n\n💰 Награда: <b>+{reward}</b> ⭐")

# --- МИНИ-ИГРЫ ---
@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🥅 Пенальти", callback_data="game_penalty")
    kb.button(text="🧩 Угадай Игрока", callback_data="game_guess")
    kb.button(text="⚔️ PvP Матч", callback_data="pvp_info")
    await message.answer("🎮 <b>Игровой зал FTCL:</b>\nВыбирай режим и зарабатывай звезды!", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data == "game_penalty")
async def pnl_init(callback: types.CallbackQuery):
    waiting_for_bet[callback.from_user.id] = "penalty"
    await callback.message.edit_text("💰 <b>Введите сумму ставки на пенальти:</b>\n(Минимум 1,000 ⭐)")

async def run_penalty(message, bet):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    if cur.fetchone()['balance'] < bet: return await message.answer("❌ У тебя недостаточно ⭐ для такой ставки!")
    kb = InlineKeyboardBuilder()
    for s, d in [("Лево ⬅️", "L"), ("Центр ⬆️", "C"), ("Право ➡️", "R")]:
        kb.button(text=s, callback_data=f"pnl_{d}_{bet}")
    await message.answer(f"🥅 Ставка <b>{bet}</b> ⭐ принята!\nВратарь готов. Куда будешь бить?", reply_markup=kb.adjust(3).as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data.startswith("pnl_"))
async def pnl_res(callback: types.CallbackQuery):
    _, _, bet = callback.data.split("_"); bet = int(bet); uid = callback.from_user.id
    conn = get_db_connection(); cur = conn.cursor()
    win = random.choice([True, False])
    if win:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, uid))
        txt = f"✅ <b>ГОООЛ!</b>\n\nТы технично переиграл вратаря!\n💰 Твой выигрыш: <b>+{bet}</b> ⭐"
    else:
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, uid))
        txt = f"❌ <b>МИМО!</b>\n\nВратарь угадал направление удара.\n📉 Ты потерял: <b>-{bet}</b> ⭐"
    conn.commit(); cur.close(); conn.close()
    await callback.message.edit_text(txt)

@dp.callback_query(F.data == "game_guess")
async def guess_init(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid in guess_cooldowns and time.time() - guess_cooldowns[uid] < 3600:
        return await callback.answer("⏳ Раунд угадайки доступен раз в час!", show_alert=True)
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
    target = cur.fetchone()
    cur.execute("SELECT name FROM all_cards WHERE name != %s ORDER BY RANDOM() LIMIT 3", (target['name'],))
    names = [target['name']] + [r['name'] for r in cur.fetchall()]
    random.shuffle(names)
    
    guess_cooldowns[uid] = time.time()
    kb = InlineKeyboardBuilder()
    for n in names: kb.button(text=n, callback_data=f"gs_{'w' if n == target['name'] else 'l'}")
    await callback.message.answer(f"🧩 <b>Угадай игрока по характеристикам:</b>\n\n🛡 Клуб: <b>{target['club']}</b>\n📊 Рейтинг: <b>{target['rating']}</b>\n🏃 Позиция: <b>{target['position']}</b>", reply_markup=kb.adjust(2).as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data.startswith("gs_"))
async def guess_res(callback: types.CallbackQuery):
    res = callback.data.split("_")[1]
    if res == 'w':
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + 2000 WHERE user_id = %s", (callback.from_user.id,))
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text("✅ <b>Верно!</b> Ты настоящий эксперт.\n💰 Награда: <b>+2000</b> ⭐")
    else: await callback.message.edit_text("❌ <b>Неправильно!</b> Это был другой футболист.")

# --- PvP МАТЧ (С КРАСИВЫМИ ТЕКСТАМИ) ---
@dp.callback_query(F.data == "pvp_info")
async def pvp_info(callback: types.CallbackQuery):
    await callback.message.answer("⚔️ <b>PvP Матч 4-3-3</b>\n\n1. Собери состав в Профиле.\n2. Напиши <code>/match [ставка]</code> в чате.\n3. Играй 5 пошаговых раундов!\n\nПобедитель забирает банк! 🏆")

@dp.message(Command("match"))
async def match_cmd(message: types.Message, command: CommandObject):
    if not command.args or not command.args.isdigit(): return await message.answer("❌ Пример: /match 5000")
    bet = int(command.args)
    uid = message.from_user.id
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    cur.execute("SELECT 1 FROM active_teams WHERE user_id = %s", (uid,))
    if not cur.fetchone(): return await message.answer("❌ Ты не собрал команду! Зайди в Профиль -> Моя Команда.")
    if u['balance'] < bet: return await message.answer("❌ Недостаточно ⭐ на балансе!")
    
    m_id = f"m_{uid}_{int(time.time())}"
    active_matches[m_id] = {"p1": uid, "p1_name": message.from_user.full_name, "p2": None, "bet": bet, "round": 1, "score": [0,0]}
    kb = InlineKeyboardBuilder().button(text=f"Принять вызов ({bet} ⭐)", callback_data=f"join_{m_id}")
    await message.answer(f"🏟 <b>{message.from_user.full_name}</b> вызывает на футбольный поединок!\n💰 Ставка: <b>{bet}</b> ⭐", reply_markup=kb.as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data.startswith("join_"))
async def join_p(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    uid = callback.from_user.id
    if not m or m['p2']: return await callback.answer("Матч уже занят!")
    if uid == m['p1']: return await callback.answer("Нельзя играть с собой!")
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    cur.execute("SELECT 1 FROM active_teams WHERE user_id = %s", (uid,))
    if not cur.fetchone(): return await callback.answer("Собери команду в профиле!", show_alert=True)
    if u['balance'] < m['bet']: return await callback.answer("Мало звезд!")

    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id IN (%s, %s)", (m['bet'], m['p1'], uid))
    conn.commit(); cur.close(); conn.close()
    
    m['p2'] = uid; m['p2_name'] = callback.from_user.full_name
    kb = InlineKeyboardBuilder().button(text="🤛 Атаковать!", callback_data=f"kick_{m_id}")
    await callback.message.edit_text(f"⚽️ <b>Матч начался!</b>\n\n🏟 {m['p1_name']} 🆚 {m['p2_name']}\n\n<i>Нажимайте кнопку для проведения атаки!</i>", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("kick_"))
async def kick_p(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    if not m or callback.from_user.id not in [m['p1'], m['p2']]: return

    atk_id = m['p1'] if m['round'] % 2 != 0 else m['p2']
    def_id = m['p2'] if m['round'] % 2 != 0 else m['p1']
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT name, rating FROM all_cards WHERE id = ANY((SELECT fwd_ids FROM active_teams WHERE user_id = %s)) ORDER BY RANDOM() LIMIT 1", (atk_id,))
    atk_p = cur.fetchone()
    cur.execute("SELECT name, rating FROM all_cards WHERE id = ANY((SELECT def_ids FROM active_teams WHERE user_id = %s)) ORDER BY RANDOM() LIMIT 1", (def_id,))
    def_p = cur.fetchone()

    goal = random.randint(1, 100) <= (50 + (atk_p['rating'] - def_p['rating']))
    if goal:
        if atk_id == m['p1']: m['score'][0] += 1
        else: m['score'][1] += 1
    
    icon = "🟢" if goal else "🔴"
    event = f"{icon} <b>{atk_p['name']}</b> прорывается по флангу... " + ("и забивает шикарный ГОЛ!" if goal else "но защита блокирует удар!")
    m['round'] += 1
    
    if m['round'] > 5:
        win_id = m['p1'] if m['score'][0] > m['score'][1] else (m['p2'] if m['score'][1] > m['score'][0] else None)
        bank = m['bet'] * 2
        if win_id: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bank, win_id))
        else: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id IN (%s, %s)", (m['bet'], m['p1'], m['p2']))
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(f"🏁 <b>Матч завершен!</b>\n\nСчёт: <b>{m['score'][0]} - {m['score'][1]}</b>\n\n🏆 Победитель: <b>{m['p1_name'] if win_id == m['p1'] else (m['p2_name'] if win_id else 'Ничья')}</b>")
        active_matches.pop(m_id, None)
    else:
        kb = InlineKeyboardBuilder().button(text="🤜 Следующий момент", callback_data=f"kick_{m_id}")
        await callback.message.edit_text(f"⚽ Раунд {m['round']-1}/5\n\n{event}\n\n📊 Счёт <b>{m['score'][0]}:{m['score'][1]}</b>", reply_markup=kb.as_markup())
        cur.close(); conn.close()

# --- СИСТЕМНОЕ ---
@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Золотой пак (5000 ⭐)", callback_data="buy_gold")
    await message.answer("🛒 <b>Магазин FTCL:</b>\nТут можно купить редкие наборы карт!", reply_markup=kb.as_markup())

@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    top = cur.fetchall(); cur.close(); conn.close()
    await message.answer("📊 <b>Мировой рейтинг игроков:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} — {r[1]} ⭐" for i, r in enumerate(top)]))

@dp.message(F.text == "Рефералка 👥")
async def ref_sys(message: types.Message):
    bot_un = (await bot.get_me()).username
    await message.answer(f"👥 <b>Реферальная система:</b>\n\nПриглашай друзей и получай <b>+1500 ⭐</b> за каждого!\n\nТвоя ссылка:\n<code>t.me/{bot_un}?start={message.from_user.id}</code>")

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
