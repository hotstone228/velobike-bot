from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from config import *
from typing import Optional, List
import datetime

# Создаем движок для подключения к БД
engine = create_engine(DATABASE_URL)
# Единая база для всех моделей
Base = declarative_base()
# Фабрика сессий
SessionLocal = sessionmaker(bind=engine)


# ================================
# Модель для таблицы accounts
# ================================
class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    login = Column(String, nullable=False)
    password = Column(String, nullable=False)
    cookie = Column(String, nullable=False)
    token = Column(String, nullable=True)  # Новый столбец token
    updated_at = Column(
        DateTime,
        default=datetime.datetime.now(datetime.timezone.utc),
        onupdate=datetime.datetime.now(datetime.timezone.utc),
    )

    def __repr__(self):
        return f"<Account(login={self.login})>"


# =======================================
# Модель для таблицы active_rides (бот)
# =======================================
class ActiveRide(Base):
    __tablename__ = "active_rides"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, unique=True)  # Telegram ID пользователя
    login = Column(String, nullable=False)  # Логин для API Velobike
    rent_id = Column(String, nullable=False)  # ID аренды, полученный от API
    device_id = Column(String, nullable=False)  # ID устройства (велосипеда)
    frame_number = Column(String, nullable=False)  # Номер велосипеда
    stop_step = Column(Integer, default=0)  # Новый столбец stop_step
    start_time = Column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.datetime.now(datetime.timezone.utc),
        onupdate=datetime.datetime.now(datetime.timezone.utc),
    )

    def __repr__(self):
        return f"<ActiveRide(user_id={self.user_id}, rent_id={self.rent_id}, frame_number={self.frame_number}, stop_step={self.stop_step})>"


# ============================================
# Модель для таблицы telegram_users (бот)
# ============================================
class TelegramUser(Base):
    __tablename__ = "telegram_users"
    telegram_id = Column(Integer, primary_key=True)  # Telegram ID пользователя
    selected_login = Column(String, nullable=True)  # Выбранный логин сервиса аренды
    approved = Column(
        Boolean, nullable=False, default=False
    )  # Разрешение пользования ботом (по умолчанию False)
    rides_count = Column(Integer, default=0, nullable=False)  # Количество поездок
    total_ride_duration = Column(
        Integer, default=0, nullable=False
    )  # Общее время поездок (в секундах)
    last_ride_date = Column(DateTime, nullable=True)  # Дата последней поездки
    registration_date = Column(
        DateTime, default=datetime.datetime.now(datetime.timezone.utc), nullable=False
    )
    username = Column(String, nullable=True)  # Telegram username
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.now(datetime.timezone.utc),
        onupdate=datetime.datetime.now(datetime.timezone.utc),
    )

    def __repr__(self):
        return f"<TelegramUser(telegram_id={self.telegram_id}, selected_login={self.selected_login}, approved={self.approved})>"


# ============================================
# Функция создания всех таблиц
# ============================================
def create_tables():
    """Создает все таблицы, определенные в моделях."""
    Base.metadata.create_all(engine)
    logger.info("Все таблицы (accounts, active_rides, telegram_users) успешно созданы.")


# ============================================
# Функция для получения сессии
# ============================================
def get_session() -> Session:
    """Возвращает новую сессию для работы с базой данных."""
    return SessionLocal()


# ============================================
# Функции для работы с таблицей Account
# ============================================
def get_account_by_login(login: str) -> Optional[Account]:
    session = get_session()
    try:
        account = session.query(Account).filter(Account.login == login).first()
        if account is None:
            logger.info(f"Аккаунт с логином '{login}' не найден.")
        return account
    except Exception as e:
        logger.error(f"Ошибка при выборке аккаунта '{login}': {e}")
        raise e
    finally:
        session.close()


def create_account(
    login: str, password: str, cookie: str, token: Optional[str] = None
) -> Account:
    session = get_session()
    try:
        account = Account(login=login, password=password, cookie=cookie, token=token)
        session.add(account)
        session.commit()
        session.refresh(account)
        logger.info(f"Аккаунт '{login}' успешно создан.")
        return account
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при создании аккаунта '{login}': {e}")
        raise e
    finally:
        session.close()


def update_account(
    login: str, cookie: Optional[str] = None, token: Optional[str] = None
) -> Optional[Account]:
    session = get_session()
    try:
        account = session.query(Account).filter(Account.login == login).first()
        if not account:
            logger.info(f"Аккаунт с логином '{login}' не найден для обновления.")
            return None
        if cookie is not None:
            account.cookie = cookie
        if token is not None:
            account.token = token
        session.commit()
        session.refresh(account)
        logger.info(f"Аккаунт '{login}' успешно обновлен.")
        return account
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при обновлении аккаунта '{login}': {e}")
        raise e
    finally:
        session.close()


def delete_account(login: str) -> bool:
    session = get_session()
    try:
        account = session.query(Account).filter(Account.login == login).first()
        if not account:
            logger.info(f"Аккаунт с логином '{login}' не найден для удаления.")
            return False
        session.delete(account)
        session.commit()
        logger.info(f"Аккаунт '{login}' успешно удален.")
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при удалении аккаунта '{login}': {e}")
        raise e
    finally:
        session.close()


def get_all_accounts() -> List[Account]:
    session = get_session()
    try:
        accounts = session.query(Account).all()
        return accounts
    except Exception as e:
        logger.error(f"Ошибка при получении списка аккаунтов: {e}")
        raise e
    finally:
        session.close()


# ============================================
# Функции для работы с таблицей ActiveRide
# ============================================
def save_ride(
    user_id: int, login: str, rent_id: str, device_id: str, frame_number: str
) -> ActiveRide:
    session = get_session()
    try:
        ride = ActiveRide(
            user_id=user_id,
            login=login,
            rent_id=rent_id,
            device_id=device_id,
            frame_number=frame_number,
        )
        session.add(ride)
        session.commit()
        session.refresh(ride)
        logger.info(f"Активная поездка для user_id {user_id} сохранена: {ride}")
        return ride
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка сохранения поездки для user_id {user_id}: {e}")
        raise e
    finally:
        session.close()


def get_ride(user_id: int) -> Optional[ActiveRide]:
    session = get_session()
    try:
        ride = session.query(ActiveRide).filter(ActiveRide.user_id == user_id).first()
        return ride
    except Exception as e:
        logger.error(f"Ошибка при получении поездки для user_id {user_id}: {e}")
        raise e
    finally:
        session.close()


def delete_ride(user_id: int) -> bool:
    session = get_session()
    try:
        ride = session.query(ActiveRide).filter(ActiveRide.user_id == user_id).first()
        if not ride:
            logger.info(
                f"Активная поездка для user_id {user_id} не найдена для удаления."
            )
            return False
        session.delete(ride)
        session.commit()
        logger.info(f"Активная поездка для user_id {user_id} успешно удалена.")
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при удалении поездки для user_id {user_id}: {e}")
        raise e
    finally:
        session.close()


def get_all_rides() -> List[ActiveRide]:
    session = get_session()
    try:
        rides = session.query(ActiveRide).all()
        return rides
    except Exception as e:
        logger.error(f"Ошибка при получении списка активных поездок: {e}")
        raise e
    finally:
        session.close()


def bump_stop_step(user_id: int) -> Optional[ActiveRide]:
    """Получает активную поездку по user_id, увеличивает stop_step на 1 и сохраняет изменения."""
    session = get_session()
    try:
        ride = session.query(ActiveRide).filter(ActiveRide.user_id == user_id).first()
        if not ride:
            logger.info(
                f"Активная поездка для user_id {user_id} не найдена для bump_stop_step."
            )
            return None
        ride.stop_step += 1
        session.commit()
        session.refresh(ride)
        logger.info(f"stop_step для user_id {user_id} увеличен до {ride.stop_step}.")
        return ride
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при bump_stop_step для user_id {user_id}: {e}")
        raise e
    finally:
        session.close()


# ============================================
# Функции для работы с таблицей TelegramUser
# ============================================
def create_telegram_user(
    telegram_id: int,
    selected_login: Optional[str] = None,
    approved: bool = False,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> TelegramUser:
    session = get_session()
    try:
        user = TelegramUser(
            telegram_id=telegram_id,
            selected_login=selected_login,
            approved=approved,
            username=username,
            first_name=first_name,
            last_name=last_name,
            registration_date=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info(f"TelegramUser {telegram_id} успешно создан: {user}")
        return user
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при создании TelegramUser {telegram_id}: {e}")
        raise e
    finally:
        session.close()


def get_telegram_user(telegram_id: int) -> Optional[TelegramUser]:
    session = get_session()
    try:
        user = (
            session.query(TelegramUser)
            .filter(TelegramUser.telegram_id == telegram_id)
            .first()
        )
        return user
    except Exception as e:
        logger.error(f"Ошибка при получении TelegramUser {telegram_id}: {e}")
        raise e
    finally:
        session.close()


def update_telegram_user(
    telegram_id: int,
    selected_login: Optional[str] = None,
    approved: Optional[bool] = None,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    rides_count: Optional[int] = None,
    total_ride_duration: Optional[int] = None,
    last_ride_date: Optional[datetime.datetime] = None,
) -> Optional[TelegramUser]:
    session = get_session()
    try:
        user = (
            session.query(TelegramUser)
            .filter(TelegramUser.telegram_id == telegram_id)
            .first()
        )
        if not user:
            logger.info(f"TelegramUser {telegram_id} не найден для обновления.")
            return None
        if selected_login is not None:
            user.selected_login = selected_login
        if approved is not None:
            user.approved = approved
        if username is not None:
            user.username = username
        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if rides_count is not None:
            user.rides_count = rides_count
        if total_ride_duration is not None:
            user.total_ride_duration = total_ride_duration
        if last_ride_date is not None:
            user.last_ride_date = last_ride_date
        session.commit()
        session.refresh(user)
        logger.info(f"TelegramUser {telegram_id} успешно обновлен: {user}")
        return user
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при обновлении TelegramUser {telegram_id}: {e}")
        raise e
    finally:
        session.close()


def delete_telegram_user(telegram_id: int) -> bool:
    session = get_session()
    try:
        user = (
            session.query(TelegramUser)
            .filter(TelegramUser.telegram_id == telegram_id)
            .first()
        )
        if not user:
            logger.info(f"TelegramUser {telegram_id} не найден для удаления.")
            return False
        session.delete(user)
        session.commit()
        logger.info(f"TelegramUser {telegram_id} успешно удален.")
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при удалении TelegramUser {telegram_id}: {e}")
        raise e
    finally:
        session.close()


def get_all_telegram_users() -> List[TelegramUser]:
    session = get_session()
    try:
        users = session.query(TelegramUser).all()
        return users
    except Exception as e:
        logger.error(f"Ошибка при получении списка TelegramUser: {e}")
        raise e
    finally:
        session.close()


# Точка входа для самостоятельного запуска скрипта (например, для создания таблиц)
if __name__ == "__main__":
    create_tables()
