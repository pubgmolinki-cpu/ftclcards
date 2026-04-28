from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List

# Импортируем твои модели из database.py
# from database import SessionLocal, Match, User, Bet

app = FastAPI()

# Настройка CORS, чтобы Web App (браузер) мог делать запросы к серверу
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # В будущем замени на URL своего сайта для безопасности
    allow_methods=["*"],
    allow_headers=["*"],
)

# Функция для получения сессии базы данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- ЭНДПОИНТЫ ДЛЯ WEB APP ---

@app.get("/api/matches")
def get_all_matches(db: Session = Depends(get_db)):
    """Отдает список всех матчей, разделенных по турам"""
    matches = db.query(Match).filter(Match.is_finished == False).all()
    # Сюда можно добавить логику группировки по турам
    return matches

@app.get("/api/user/{tg_id}")
def get_user_profile(tg_id: int, db: Session = Depends(get_db)):
    """Отдает данные профиля: баланс и историю для графика"""
    user = db.query(User).filter(User.tg_id == tg_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # history возвращаем как список чисел для отрисовки графика в Web App
    return {
        "nickname": user.nickname,
        "balance": user.balance,
        "history": user.history.split(",") if user.history else []
    }

@app.post("/api/bet")
def place_bet(user_id: int, match_id: int, amount: float, prediction: str, db: Session = Depends(get_db)):
    """Логика совершения ставки"""
    match = db.query(Match).filter(Match.id == match_id).first()
    user = db.query(User).filter(User.id == user_id).first()

    # 1. Проверка: не закончилось ли время (Таймер закрытия линий)
    if datetime.now() > match.deadline:
        raise HTTPException(status_code=400, detail="Линия закрыта! Время вышло.")

    # 2. Проверка: хватает ли денег
    if user.balance < amount:
        raise HTTPException(status_code=400, detail="Недостаточно TonBox Coins")

    # 3. Создание ставки
    # Выбираем нужный коэффициент в зависимости от прогноза
    coeff = getattr(match, f"k_{prediction.lower()}") # берет k_p1, k_x или k_p2

    new_bet = Bet(
        user_id=user.id,
        match_id=match.id,
        amount=amount,
        prediction=prediction,
        coeff=coeff
    )
    
    user.balance -= amount
    db.add(new_bet)
    db.commit()
    
    return {"status": "success", "new_balance": user.balance}

@app.get("/api/info")
def get_info(db: Session = Depends(get_db)):
    """Отдает текстовую информацию/новости для раздела Информация"""
    # Здесь можно возвращать текст из специальной таблицы новостей
    return {"text": "Добро пожаловать в TonBoxBet! Сегодня стартует ЧМ!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
