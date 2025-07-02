import asyncio
import re
import aiohttp
import cv2
import numpy as np
from pyzbar.pyzbar import decode

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.filters.callback_data import CallbackData
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Импорт функций работы с БД для Telegram-пользователей и активных поездок
from database import *
import io
from config import *
from enum import Enum

# ---------------------------
# Настройка бота и логгирования
# ---------------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()  # В aiogram v3 Dispatcher и Router используются для маршрутизации

# ---------------------------
# Inline и Reply клавиатуры
# ---------------------------
stop_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⛔СТОП")]],
    resize_keyboard=True,
    one_time_keyboard=False,
)


# 1. Enum для действий
class Action(str, Enum):
    start = "start"
    stop = "stop"
    omni = "omni"
    chain = "chain"
    account = "account"


# 2. CallbackData класс с префиксом
class VeloCallback(CallbackData, prefix="velo"):
    action: Action
    frame: str | None = None
    login: str | None = None


# ---------------------------
# Middleware для логирования входящих сообщений
# ---------------------------
class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        message = event

        # Проверяем, существует ли пользователь в базе данных
        user = get_telegram_user(message.from_user.id)
        if not user:
            # Если пользователь не найден, добавляем его с настройками по умолчанию
            create_telegram_user(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                approved=False,  # По умолчанию доступ запрещен
            )
            logger.info(
                f"Новый пользователь добавлен в базу данных: {message.from_user.id} {message.text}"
            )
            await message.answer(
                "🆕 Пользователь добавлен в базу данных. Ожидается подтверждение от администратора."
            )
            return
        else:
            if not user.approved:
                logger.info(
                    f"Доступ запрещен для пользователя: {message.from_user.id} {message.text}"
                )
                await message.answer("❌ Доступ запрещен. Обратитесь к администратору.")
                return
        return await handler(event, data)


# ---------------------------
# Регистрация middleware
# ---------------------------
dp.message.middleware(LoggingMiddleware())


# ---------------------------
# Вспомогательная функция для вызова API-сервера
# ---------------------------
async def call_api(method: str, endpoint: str, *, params=None, json=None, data=None):
    url = f"{API_BASE_URL}{endpoint}"
    async with aiohttp.ClientSession() as session:
        async with session.request(
            method, url, params=params, json=json, data=data
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                detail = await resp.text()
                raise Exception(f"API error {resp.status}: {detail}")


# ---------------------------
# Обработка ввода номера велосипеда (текст или фото)
# ---------------------------
async def remove_inline_keyboard(chat_id: int, message_id: int):
    try:
        await asyncio.sleep(300)  # Ждем 5 минут
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )
    except Exception as e:
        logger.error(f"Inline keyboard removal error: {e}")


def get_ride_keboard(
    bike_code: str, minutes: int = 30, seconds: int = 0
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔓ЗАДНЕЕ КОЛЕСО",
        callback_data=VeloCallback(action=Action.omni, frame=bike_code),
    )
    builder.button(
        text="🔓ТРОС СПЕРЕДИ",
        callback_data=VeloCallback(action=Action.chain, frame=bike_code),
    )
    builder.button(
        text=f"⛔{minutes:02d}:{seconds:02d}",
        callback_data=VeloCallback(action=Action.stop, frame=bike_code),
    )
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------
# Функция получения выбранного логина из базы
# ---------------------------
def get_user_login(chat_id: int) -> str:
    user = get_telegram_user(chat_id)
    if not user or not user.selected_login:
        raise Exception("Логин не выбран. Используйте команду /setlogin")
    return user.selected_login


# ---------------------------
# Автоматическое завершение поездки (с повторными попытками)
# ---------------------------
async def auto_finish_ride(chat_id: int, rentId):
    await asyncio.sleep(1 * 60)
    max_retries = 5
    delay = 10
    for attempt in range(1, max_retries + 1):
        try:
            await stop_ride_handler(chat_id, rentId)
            await bot.send_message(
                chat_id,
                text=f"Поездка {rentId} автоматически завершена",
            )
            return
        except Exception as e:
            logger.error(f"Автозавершение (попытка {attempt}) не удалось: {e}")
            if attempt < max_retries:
                await asyncio.sleep(delay)
            else:
                await bot.send_message(
                    chat_id,
                    text=f"Не удалось автоматически завершить поездку {rentId}. Пожалуйста, попробуйте вручную /stop",
                )
                return


# ---------------------------
# Функция построения inline клавиатуры со всеми velobike аккаунтами
# ---------------------------
def get_accounts_keyboard(login: str | None = None) -> InlineKeyboardMarkup:
    accounts = get_all_accounts()  # Получаем список аккаунтов из базы данных
    builder = InlineKeyboardBuilder()
    for account in accounts:
        builder.button(
            text=account.login if account.login != login else f"{account.login} ✅",
            callback_data=VeloCallback(action=Action.account, login=account.login),
        )
    builder.adjust(2)
    return builder.as_markup()


async def countdown_timer(chat_id: int, message_id: int, ride_id: str):
    """
    Обновляет сообщение с обратным отсчетом от 30 минут до 0.
    Каждые 30 секунд проверяет, существует ли еще активная поездка.
    Если поездка отменена, завершаем таймер.
    """
    total_seconds = 29 * 60  # 30 минут в секундах
    update_interval = 30  # обновляем каждые 30 секунд

    remaining = total_seconds
    while remaining > 0:
        # Проверяем, что поездка ещё активна
        if not get_ride(chat_id):
            break

        minutes, seconds = divmod(remaining, 60)
        ride_keyboard = get_ride_keboard(ride_id, minutes, seconds)
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=ride_keyboard,
            )
        except Exception as ex:
            logger.error(f"Не удалось обновить обратный отсчёт: {ex}")
        await asyncio.sleep(update_interval)
        remaining -= update_interval


# ---------------------------
# Универсальный обработчик остановки поездки
# ---------------------------
async def stop_ride_handler(chat_id: int, rentId: str | None = None):
    ride = get_ride(chat_id)
    if not ride:
        raise Exception("Нет активной поездки")
    if rentId and ride.rent_id != rentId:
        raise Exception("Номер поездки не совпадает")
    # Подготовка полезных данных из базы
    finish_payload = {
        "login": ride.login,
        "rentId": ride.rent_id,
        "clientGeoPosition": {"lat": 0, "lon": 0},
    }
    park_payload = {
        "login": ride.login,
        "rentId": ride.rent_id,
        "deviceId": ride.device_id,
        "externalParkingId": "undefined",
    }
    finish_after_payload = {
        "login": ride.login,
        "rentId": ride.rent_id,
        "clientGeoPosition": {"lat": 0, "lon": 0},
    }
    if ride.stop_step == 0:
        # 1. Завершение аренды
        finish_result = await call_api("POST", "/rent/finish", json=finish_payload)
        if finish_result:
            bump_stop_step(ride.user_id)
        logger.debug(finish_result)
    if ride.stop_step == 1:
        # 2. Парковка велосипеда
        park_result = await call_api("POST", "/rent/park", json=park_payload)
        if park_result:
            bump_stop_step(ride.user_id)
        logger.debug(park_result)
    if ride.stop_step == 2:
        # 3. Загрузка фото (используем поддельное изображение)
        fake_image = io.BytesIO(b"fake_image_data")
        form = aiohttp.FormData()
        form.add_field(
            "photo",
            fake_image.read(),
            filename=f"{ride.rent_id}.jpg",
            content_type="image/jpeg",
        )
        # В запросе для загрузки фото параметры передаются через query-параметры
        upload_params = {
            "login": ride.login,
            "rentId": ride.rent_id,
            "deviceId": ride.device_id,
        }
        upload_result = await call_api(
            "POST", "/rent/upload_photo", params=upload_params, data=form
        )
        if upload_result:
            bump_stop_step(ride.user_id)
        logger.debug(upload_result)

    if ride.stop_step == 3:
        # 4. Завершение аренды после загрузки фото
        finish_after_result = await call_api(
            "POST", "/rent/finish_after_upload", json=finish_after_payload
        )
        if finish_after_result:
            bump_stop_step(ride.user_id)
        logger.debug(finish_after_result)
    # После успешного выполнения всех шагов – удаляем поездку
    delete_ride(chat_id)
    return ride.rent_id


# ---------------------------
# Команда установки логина (/setlogin)
# Если команда вызвана без аргументов, выводит инлайн-клавиатуру со списком доступных аккаунтов
# ---------------------------
@dp.message(Command("setlogin"))
async def set_login(message: types.Message, command: CommandObject):
    args = command.args
    user = get_telegram_user(message.from_user.id)
    if not args:
        keyboard = get_accounts_keyboard(user.selected_login)
        await message.answer(
            text=f"🆔 Выберите логин для аренды:",
            reply_markup=keyboard,
        )
        return
    login = args.strip()
    update_telegram_user(message.from_user.id, selected_login=login)
    await message.answer(text=f"✅ Ваш логин для аренды установлен: <b>{login}</b>")


# ---------------------------
# Команда /start
# ---------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    args = command.args
    if args:
        await handle_bike_input(message)
    else:
        await message.answer(
            text="✅ Бот запущен\nДля установки логина используйте /setlogin",
            reply_markup=stop_keyboard,
        )


@dp.message(F.photo | F.text.regexp(r"\d{5}"))
async def handle_bike_input(message: types.Message):
    chat_id = message.chat.id
    try:
        bike_code = ""
        if message.photo:
            file_info = await bot.get_file(message.photo[-1].file_id)
            file_bytes = await bot.download_file(file_info.file_path)
            arr = np.asarray(bytearray(file_bytes.read()), dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            decoded_objs = decode(img)
            if decoded_objs:
                m = re.search(r"\d{5}", decoded_objs[0].data.decode())
                if m:
                    bike_code = m.group()
        else:
            m = re.search(r"\d{5}", message.text)
            if m:
                bike_code = m.group()
        if not bike_code:
            await message.answer(text="❌ Не удалось распознать номер велосипеда")
            return

        login = get_user_login(chat_id)
        params = {"login": login}
        vehicle_info = await call_api("GET", f"/vehicle/{bike_code}", params=params)
        if vehicle_info.get("operativeStatus") != "STATIONED":
            await message.answer(text="❌ Велосипед недоступен для аренды")
            return
        if vehicle_info.get("deviceType") == "OMNI_IOT_DEVICE":
            new = "🆕"
        else:
            new = ""
        builder = InlineKeyboardBuilder()
        builder.button(
            text="✅ СТАРТ",
            callback_data=VeloCallback(action=Action.start, frame=bike_code),
        )
        kb = builder.as_markup()
        sent_msg = await message.answer(
            text=f"{new}<b>Велосипед готов к аренде!</b>\n\n<b>🆔 Информация:</b>\n• Номер рамы: <code>{vehicle_info['frameNumber']}</code>\n• Заряд батареи: 🔋 <b>{vehicle_info['batteryPower']}%</b>\n• Пробег за поездку: <b>{vehicle_info['singleRidingMileage']} км</b>\n\n<b>📍 Текущее местоположение:</b>\n• Адрес парковки: <b>{', '.join([i['name'] for i in sorted(vehicle_info['zones'],key=lambda x:x['id'])])}</b>\n\nНажмите 'СТАРТ' для начала поездки",
            reply_markup=kb,
        )
        # Запускаем задачу на удаление клавиатуры через 5 минут,
        # если она не была удалена до этого (например, после нажатия).
        asyncio.create_task(remove_inline_keyboard(chat_id, sent_msg.message_id))
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        await message.answer(text=f"❌ Ошибка:\n{e}")


# ---------------------------
# Callback для выбора логина из инлайн-клавиатуры
# ---------------------------
@dp.callback_query(VeloCallback.filter(F.action == Action.account))
async def process_account_selection(
    callback: types.CallbackQuery, callback_data: VeloCallback
):
    selected_login = callback_data.login
    update_telegram_user(callback.message.chat.id, selected_login=selected_login)
    await callback.message.edit_text(
        text=f"✅ Ваш логин для аренды установлен: {selected_login}"
    )


# ---------------------------
# Callback для старта поездки (номер велосипеда)
# ---------------------------
@dp.callback_query(VeloCallback.filter(F.action == Action.start))
async def callback_start_ride(
    callback: types.CallbackQuery, callback_data: VeloCallback
):
    chat_id = callback.message.chat.id
    bike_code = callback_data.frame
    try:
        await callback.message.edit_text(
            text="⏳ Запускается поездка", reply_markup=None
        )
        login = get_user_login(chat_id)
        payload = {
            "login": login,
            "bikeSerialNumber": bike_code,
            "clientGeoPosition": {"lat": 0, "lon": 0},
        }
        ride_data = await call_api("POST", "/rent/rents", json=payload)
        # ride_data = {"rentId": "1", "deviceId": "1", "frameNumber": "1"}
        if ride_data.get("failedReason") == "ACCOUNT_BLOCKED":
            raise Exception("На аккаунте имеются задолженности, или не оплачен тариф")
        save_ride(
            chat_id,
            login,
            ride_data["rentId"],
            ride_data["deviceId"],
            ride_data.get("frameNumber", bike_code),
        )
        ride_keyboard = get_ride_keboard(bike_code)
        await callback.message.edit_text(
            text=f"🚲 Поездка {ride_data.get('frameNumber', bike_code)} начата\nИспользуйте кнопки ниже для управления:",
            reply_markup=ride_keyboard,
        )
        # Запускаем задачу автоматического завершения поездки
        asyncio.create_task(auto_finish_ride(chat_id, ride_data["rentId"]))
        # Запускаем задачу обратного отсчёта таймера (30 минут)
        asyncio.create_task(
            countdown_timer(chat_id, callback.message.message_id, ride_data["rentId"])
        )
    except Exception as e:
        logger.error(f"Ошибка при запуске поездки: {e}")
        await callback.message.answer(text=f"❌ Ошибка при запуске поездки:\n{e}")


# ---------------------------
# Callback для открытия замка (omni / chain)
# ---------------------------
@dp.callback_query(VeloCallback.filter(F.action == Action.omni))
@dp.callback_query(VeloCallback.filter(F.action == Action.chain))
async def callback_open_lock(
    callback: types.CallbackQuery, callback_data: VeloCallback
):
    chat_id = callback.message.chat.id
    lock_type = callback_data.action
    try:
        ride = get_ride(chat_id)
        if not ride:
            await callback.answer(text="Нет активной поездки.", show_alert=True)
            return
        payload = {
            "login": ride.login,
            "rentId": ride.rent_id,
            "deviceId": ride.device_id,
            "lockType": lock_type,
        }
        result = await call_api("POST", "/rent/open_lock", json=payload)
        await callback.answer(text="✅ Замок открыт.")
        logger.info(f"Замок для поездки {ride.rent_id} открыт: {result}")
    except Exception as e:
        logger.error(f"Ошибка открытия замка: {e}")
        await callback.message.answer(text=f"❌ Ошибка:\n{e}")


# ---------------------------
# Универсальный обработчик остановки поездки (callback и текстовая команда)
# ---------------------------
@dp.message(F.text.lower().contains("стоп"))
@dp.message(Command("stop"))
@dp.callback_query(VeloCallback.filter(F.action == Action.stop))
async def stop_ride_handler_unified(event: types.Message | types.CallbackQuery):
    try:
        if isinstance(event, types.CallbackQuery):
            chat_id = event.message.chat.id
            reply_obj = event.message
            await event.answer()
        else:
            chat_id = event.chat.id
            reply_obj = await event.answer(text="⌛Завершаю поездку...")
        await stop_ride_handler(chat_id)
    except Exception as e:
        logger.error(f"Ошибка при завершении поездки: {e}")
        await reply_obj.answer(text=f"❌ Ошибка при завершении поездки:\n{e}")


# ---------------------------
# Запуск бота
# ---------------------------
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
