import asyncio, psycopg2, os, html, random, time
from datetime import datetime, timedelta
import pytz 
from psycopg2.extras import DictCursor
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859))
PORT = int(os.getenv("PORT", 8080))

CHANNELS = ["@ftclcardschannel", "@Dempik_lega", "@waxteamiftl"]
VIP_PRICE = 15000
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Кэши и состояния
cooldowns = {}          
penalty_cooldowns = {}  
pvp_cooldowns = {}      # КД для PvP (40 минут)
temp_photo_buffer = {}  
waiting_for_bet = {}    
active_duels = {}       

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def get_now_msk():
    return datetime.now(MOSCOW_TZ)

async def check_subscription(user_id):
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

def get_vip_info(user_id):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT vip_until FROM users WHERE user_id = %s", (user_id,))
        res = cur.fetchone()
        now = get_now_msk()
        if res and res['vip_until']:
            vd = res['vip_until']
            if vd.tzinfo is None: vd = MOSCOW_TZ.localize(vd)
            if vd > now: return True, vd
        return False, None
    finally: cur.close(); conn.close()

# --- ВЕБ-СЕРВЕР ---
async def handle(request): return web.Response(text="Bot Active")
async def start_webserver():
    app = web.Application(); app.router.add_get("/", handle)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

# --- ЛОГИКА PvP С КД 40 МИНУТ ---

@dp.message(Command("duel"))
async def cmd_duel(message: types.Message):
    if not message.reply_to_message:
        return await message.reply("❌ Чтобы вызвать на дуэль, <b>ответьте (Reply)</b> на сообщение игрока! (/duel в группу где есть бот)")
    
    p1, p2 = message.from_user, message.reply_to_message.from_user
    if p1.id == p2.id: return await message.reply("❌ Нельзя играть с собой.")

    # Проверка КД вызывающего (40 минут = 2400 секунд)
    now = time.time()
    if p1.id in pvp_cooldowns and now - pvp_cooldowns[p1.id] < 2400:
        rem = int((2400 - (now - pvp_cooldowns[p1.id])) // 60)
        return await message.reply(f"⏳ Вы недавно участвовали в дуэли. Подождите еще {rem} мин.")
    
    kb = InlineKeyboardBuilder().button(text="Принять Вызов ✅", callback_data=f"pvp_acc_{p1.id}").as_markup()
    await message.answer(f"⚽️ {p1.mention_html()} вызывает {p2.mention_html()} на дуэль!", reply_markup=kb)

@dp.callback_query(F.data.startswith("pvp_acc_"))
async def pvp_accept(callback: types.CallbackQuery):
    p1_id = int(callback.data.split("_")[2])
    p2_id = callback.from_user.id
    
    # Проверка КД того, кто принимает
    now = time.time()
    if p2_id in pvp_cooldowns and now - pvp_cooldowns[p2_id] < 2400:
        rem = int((2400 - (now - pvp_cooldowns[p2_id])) // 60)
        return await callback.answer(f"⏳ Вы сможете играть через {rem} мин.", show_alert=True)

    waiting_for_bet[p2_id] = {"type": "pvp", "opponent": p1_id}
    await callback.message.edit_text("💰 <b>Вызов принят! Введите сумму ставки (от 500 ⭐):</b>")

async def pvp_init(message: types.Message):
    # (Внутри функции инициализации матча)
    # При успешном старте матча обновляем КД обоим
    p2_id = message.from_user.id
    p1_id = waiting_for_bet[p2_id]['opponent']
    pvp_cooldowns[p1_id] = time.time()
    pvp_cooldowns[p2_id] = time.time()
    # ... далее код создания дуэли d_id и т.д.

# --- ВСЕ ОСТАЛЬНЫЕ ХЕНДЛЕРЫ (ГЛАВНОЕ МЕНЮ, МАГАЗИН, КАРТЫ) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id; ref_id = command.args
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (user_id, message.from_user.username or "Игрок"))
    if ref_id and ref_id.isdigit() and int(ref_id) != user_id:
        cur.execute("UPDATE users SET balance = balance + 1500 WHERE user_id = %s", (int(ref_id),))
    conn.commit(); cur.close(); conn.close()
    kb = ReplyKeyboardBuilder()
    for b in ["Получить Карту 🏆", "Мини-Игры ⚽", "Магазин 🛒", "Профиль 👤", "Реферальная Система 👥", "ТОП-10 📊"]: kb.button(text=b)
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🥅 Пенальти (Бот x2)", callback_data="game_bot_penalty")
    kb.button(text="🔫 PvP Дуэль (1vs1)", callback_data="game_pvp_info")
    kb.adjust(1)
    await message.answer("🎯 <b>Выберите режим игры:</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "game_pvp_info")
async def pvp_info_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "⚔️ <b>PvP Дуэль (Пенальти 1 на 1)</b>\n\n"
        "Ответь на сообщение игрока командой: <code>/duel</code>\n\n"
        "⏳ <b>КД: 40 минут</b> между играми.",
        reply_markup=InlineKeyboardBuilder().button(text="Назад 🔙", callback_data="back_to_games").as_markup()
    )

# ... [ОСТАЛЬНОЙ КОД (Магазин, Профиль, Логика ударов PvP) остается таким же, как в предыдущем сообщении] ...

async def main():
    asyncio.create_task(start_webserver())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
