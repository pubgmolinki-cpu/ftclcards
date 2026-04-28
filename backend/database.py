from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True)
    nickname = Column(String)
    balance = Column(Float, default=1000.0)
    # Статистика для графика
    history = Column(String)  # Храним как JSON-строку: "[1000, 1200, 1100...]"

class Match(Base):
    __tablename__ = 'matches'
    id = Column(Integer, primary_key=True)
    tour_name = Column(String)  # Например: "1 тур ФТКЛ"
    team1_name = Column(String)
    team2_name = Column(String)
    k_p1 = Column(Float)
    k_x = Column(Float)
    k_p2 = Column(Float)
    deadline = Column(DateTime)
    is_finished = Column(Boolean, default=False)
    result = Column(String, nullable=True) # "P1", "X", "P2"

class Bet(Base):
    __tablename__ = 'bets'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    match_id = Column(Integer, ForeignKey('matches.id'))
    amount = Column(Float)
    prediction = Column(String) # "P1", "X", "P2"
    coeff = Column(Float) # Фиксируем кэф на момент ставки
