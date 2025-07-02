from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Tuple, Optional, Dict
import aiohttp
from sqlalchemy.orm import Session
from yarl import URL
from database import *
from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI(title="Velobike API Gateway", version="1.0")


# ---------------------------
# Модели запросов/ответов для API бота
# ---------------------------
class AuthRequest(BaseModel):
    login: str
    password: str


class AuthResponse(BaseModel):
    token: str  # Например, "Bearer <token>"
    cookie: str
    message: str = "Authentication successful"


class SearchRequest(BaseModel):
    login: str
    necorner: Tuple[float, float]
    swcorner: Tuple[float, float]


class RentRequest(BaseModel):
    login: str
    bikeSerialNumber: str
    clientGeoPosition: Dict[str, float]  # {"lat": float, "lon": float}


class FinishRentRequest(BaseModel):
    login: str
    rentId: str
    clientGeoPosition: Dict[str, float]


class OpenLockRequest(BaseModel):
    login: str
    rentId: str
    deviceId: str
    lockType: str  # "omni" или "chain"


class ParkRequest(BaseModel):
    login: str
    rentId: str
    deviceId: str
    externalParkingId: Optional[str] = "undefined"


class RentStatusQuery(BaseModel):
    login: str
    rentId: str
    deviceId: str


class TransportsRequest(BaseModel):
    login: str = "2757073"
    northEast: Dict[str, float]  # например: {"latitude": 55.75, "longitude": 37.62}
    southWest: Dict[str, float]


# ---------------------------
# Функция для получения аккаунта из БД
# ---------------------------
def get_account_by_login(login: str) -> Account:
    session: Session = get_session()
    try:
        account = session.query(Account).filter(Account.login == login).first()
        if account is None:
            logger.info(f"Account with login '{login}' not found.")
        return account
    except Exception as e:
        logger.error(f"Error retrieving account '{login}': {e}")
        raise e
    finally:
        session.close()


# ---------------------------
# Вспомогательная функция: создание aiohttp сессии с данными аккаунта
# ---------------------------
def get_service_session(account: Account) -> aiohttp.ClientSession:
    # Формируем заголовки, включая актуальный токен
    headers = HEADERS.copy()
    headers["Authorization"] = "Bearer " + account.token
    jar = aiohttp.CookieJar()
    jar.update_cookies(
        {"qrator_jsid": account.cookie}, response_url=URL("https://pwa.velobike.ru")
    )
    return aiohttp.ClientSession(headers=headers, cookie_jar=jar)


# ---------------------------
# Эндпоинты API
# ---------------------------
@app.get("/api/v1/accounts")
async def list_accounts():
    """
    GET /api/v1/accounts
    Возвращает список всех аккаунтов из базы данных.
    """
    try:
        accounts = get_all_accounts()
        # Преобразуем аккаунты в список словарей с нужными полями
        accounts_data = [
            {"login": acc.login, "cookie": acc.cookie, "token": acc.token}
            for acc in accounts
        ]
        return {"accounts": accounts_data}
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.post("/api/v1/search")
async def api_search(req: TransportsRequest):
    """
    POST /api/v1/search
    Ищет велосипеды по заданным границам.
    Принимает JSON:
      {
          "login": "user",
          "northEast": {"latitude": float, "longitude": float},
          "southWest": {"latitude": float, "longitude": float}
      }
    """
    # Извлекаем кортежи координат (предполагается, что словари содержат два значения)
    necorner = tuple(req.northEast.values())
    swcorner = tuple(req.southWest.values())
    logger.info(f"Search request for {req.login} with bounds {necorner} / {swcorner}")

    account = get_account_by_login(req.login)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    json_payload = {
        "inventoryStatus": ["IN_CITY"],
        "operativeStatuses": ["STATIONED", "INACTIVE"],
        "boundingBox": {
            "swCorner": {"longitude": swcorner[1], "latitude": swcorner[0]},
            "neCorner": {"longitude": necorner[1], "latitude": necorner[0]},
        },
    }
    async with get_service_session(account) as session:
        async with session.post(
            "https://pwa.velobike.ru/api/iot/cache/vehicles/search", json=json_payload
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                # logger.debug(f"/api/v1/search response: {data}")  # Added debug log
                return data.get("values", [])
            else:
                detail = await resp.text()
                logger.debug(f"/api/v1/search error: {detail}")  # Added debug log
                raise HTTPException(status_code=resp.status, detail=detail)


@app.get("/api/v1/vehicle/{vehicle_id}")
async def get_vehicle(vehicle_id: str, login: str = Query(...)):
    """
    GET /api/v1/vehicle/{vehicle_id}
    Возвращает информацию о конкретном велосипеде.
    """
    logger.info(f"Vehicle data request for vehicle {vehicle_id} by {login}")
    account = get_account_by_login(login)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    url = f"https://pwa.velobike.ru/api/iot/cache/vehicles/{vehicle_id}"
    async with get_service_session(account) as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                logger.debug(
                    f"/api/v1/vehicle/{vehicle_id} response: {data}"
                )  # Added debug log
                return data
            elif resp.status == 404:
                logger.debug(
                    f"/api/v1/vehicle/{vehicle_id} not found"
                )  # Added debug log
                return {"status": False}
            else:
                detail = await resp.text()
                logger.debug(
                    f"/api/v1/vehicle/{vehicle_id} error: {detail}"
                )  # Added debug log
                raise HTTPException(status_code=resp.status, detail=detail)


@app.post("/api/v1/rent/finish")
async def finish_rent(finish_req: FinishRentRequest):
    """
    POST /api/v1/rent/finish
    Завершает аренду.
    """
    logger.info(
        f"Finish rent request from {finish_req.login} for rent {finish_req.rentId}"
    )
    account = get_account_by_login(finish_req.login)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    url = f"https://pwa.velobike.ru/api/rent/rents/{finish_req.rentId}/finishRent"
    payload = {"clientGeoPosition": finish_req.clientGeoPosition}
    async with get_service_session(account) as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                json_data = await resp.json()
                logger.debug(
                    f"/api/v1/rent/finish response: {json_data}"
                )  # Added debug log
                return json_data
            elif resp.status == 404:
                json_data = await resp.json()
                logger.debug(f"/api/v1/rent/finish error: {json_data}")
                return False
            else:
                detail = await resp.text()
                logger.debug(f"/api/v1/rent/finish error: {detail}")  # Added debug log
                raise HTTPException(status_code=resp.status, detail=detail)


@app.post("/api/v1/rent/upload_photo")
async def upload_photo(
    login: str = Query(...),
    rentId: str = Query(...),
    deviceId: str = Query(...),
    file: UploadFile = File(...),
):
    """
    POST /api/v1/rent/upload_photo
    Загружает фото для завершения аренды.
    """
    logger.info(f"Upload photo request from {login} for rent {rentId}")
    account = get_account_by_login(login)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    url = f"https://pwa.velobike.ru/api/rent/files/{rentId}/uploadPhoto?deviceId={deviceId}"
    # Формируем multipart/form-data
    form = aiohttp.FormData()
    contents = await file.read()
    form.add_field(
        "photo", contents, filename=f"{rentId}.jpg", content_type="image/jpeg"
    )
    async with get_service_session(account) as session:
        async with session.post(url, data=form) as resp:
            if resp.status == 200:
                json_data = await resp.json()
                logger.debug(
                    f"/api/v1/rent/upload_photo response: {json_data}"
                )  # Added debug log
                return {
                    "message": "Photo uploaded successfully",
                    "rentId": rentId,
                    "data": json_data,
                }
            else:
                detail = await resp.text()
                logger.debug(
                    f"/api/v1/rent/upload_photo error: {detail}"
                )  # Added debug log
                raise HTTPException(status_code=resp.status, detail=detail)


@app.post("/api/v1/rent/open_lock")
async def open_lock(open_lock_req: OpenLockRequest):
    """
    POST /api/v1/rent/open_lock
    Открывает замок велосипеда.
    """
    logger.info(
        f"Open lock request from {open_lock_req.login} for rent {open_lock_req.rentId} with lock type {open_lock_req.lockType}"
    )
    account = get_account_by_login(open_lock_req.login)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if open_lock_req.lockType.lower() == "omni":
        url = f"https://pwa.velobike.ru/api/rent/rents/{open_lock_req.rentId}/commands/openOmniLock"
    elif open_lock_req.lockType.lower() == "chain":
        url = f"https://pwa.velobike.ru/api/rent/rents/{open_lock_req.rentId}/commands/openChainLock"
    else:
        raise HTTPException(status_code=400, detail="Invalid lock type")
    payload = {"deviceId": open_lock_req.deviceId}
    async with get_service_session(account) as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                json_data = await resp.json()
                logger.debug(
                    f"/api/v1/rent/open_lock response: {json_data}"
                )  # Added debug log
                return {
                    "message": f"{open_lock_req.lockType.capitalize()} lock opened successfully",
                    "rentId": open_lock_req.rentId,
                    "data": json_data,
                }
            else:
                detail = await resp.text()
                logger.debug(
                    f"/api/v1/rent/open_lock error: {detail}"
                )  # Added debug log
                raise HTTPException(status_code=resp.status, detail=detail)


@app.post("/api/v1/rent/park")
async def park_bike(park_req: ParkRequest):
    """
    POST /api/v1/rent/park
    Паркует велосипед.
    """
    logger.info(f"Park bike request from {park_req.login} for rent {park_req.rentId}")
    account = get_account_by_login(park_req.login)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    url = f"https://pwa.velobike.ru/api/rent/rents/{park_req.rentId}/commands/parkBikeToParking"
    payload = {
        "deviceId": park_req.deviceId,
        "externalParkingId": park_req.externalParkingId,
    }
    async with get_service_session(account) as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                json_data = await resp.json()
                logger.debug(
                    f"/api/v1/rent/park response: {json_data}"
                )  # Added debug log
                return {
                    "message": "Bike parked successfully",
                    "rentId": park_req.rentId,
                    "data": json_data,
                }
            else:
                error_data = await resp.json()
                logger.debug(
                    f"/api/v1/rent/park error: {error_data}"
                )  # Added debug log
                if (
                    error_data.get("status") == 400
                    and error_data.get("detail")
                    == "Wrong rent substatus D0_GET_POSITIONING"
                ):
                    raise HTTPException(
                        status_code=400, detail=error_data.get("detail")
                    )
                raise HTTPException(status_code=resp.status, detail=str(error_data))


@app.get("/api/v1/rent/status")
async def check_rent_status(
    login: str = Query(...), rentId: str = Query(...), deviceId: str = Query(...)
):
    """
    GET /api/v1/rent/status
    Проверяет статус аренды.
    """
    logger.info(f"Check rent status request from {login} for rent {rentId}")
    account = get_account_by_login(login)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    url = f"https://pwa.velobike.ru/api/rent/rents/{rentId}/checkRentStatus?frameNumber={deviceId}"
    async with get_service_session(account) as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                logger.debug(f"/api/v1/rent/status response: {data}")  # Added debug log
                return data
            else:
                detail = await resp.text()
                logger.debug(f"/api/v1/rent/status error: {detail}")  # Added debug log
                raise HTTPException(status_code=resp.status, detail=detail)


# Добавляем следующие эндпоинты в файл api.py


# 1. Завершение аренды после загрузки фото (finishRentAfterUploadPhoto)
@app.post("/api/v1/rent/finish_after_upload")
async def finish_rent_after_upload(req: FinishRentRequest):
    """
    POST /api/v1/rent/finish_after_upload
    Завершает аренду после загрузки фото.
    Требует: login, rentId, clientGeoPosition.
    """
    logger.info(f"Finish after upload request for rent {req.rentId} by {req.login}")
    account = get_account_by_login(req.login)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    url = f"https://pwa.velobike.ru/api/rent/rents/{req.rentId}/finishRentAfterUploadPhoto"
    async with get_service_session(account) as session:
        async with session.post(url, json={"login": req.login}) as resp:
            if resp.status == 200:
                json_data = await resp.json()
                logger.debug(
                    f"/api/v1/rent/finish_after_upload response: {json_data}"
                )  # Added debug log
                return json_data
            elif resp.status == 404:
                json_data = await resp.json()
                logger.debug(
                    f"/api/v1/rent/finish_after_upload error: {json_data}"
                )  # Added debug log
                return False
            else:
                detail = await resp.text()
                logger.debug(
                    f"/api/v1/rent/finish_after_upload error: {detail}"
                )  # Added debug log
                raise HTTPException(status_code=resp.status, detail=detail)


# 2. Получение незавершённой поездки (rents_not_finished_user)
@app.get("/api/v1/rent/not_finished")
async def rents_not_finished_user(login: str = Query(...)):
    """
    GET /api/v1/rent/not_finished
    Возвращает информацию о незавершённой поездке пользователя.
    Если поездок нет, возвращает False.
    """
    logger.info(f"Not finished rent request for login {login}")
    account = get_account_by_login(login)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    async with get_service_session(account) as session:
        async with session.get(
            "https://pwa.velobike.ru/api/rent/rents/not-finished/user"
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                logger.debug(
                    f"/api/v1/rent/not_finished response: {data}"
                )  # Added debug log
                if not data:
                    return False
                return data[0]
            else:
                detail = await resp.text()
                logger.debug(
                    f"/api/v1/rent/not_finished error: {detail}"
                )  # Added debug log
                raise HTTPException(status_code=resp.status, detail=detail)


# 3. Альтернативный запуск аренды (rent_rents)
@app.post("/api/v1/rent/rents")
async def rent_rents(req: RentRequest):
    """
    POST /api/v1/rent/rents
    Запускает аренду велосипеда (альтернативный метод).
    Требует: login, bikeSerialNumber, clientGeoPosition.
    Если API возвращает статус "ERROR_START", выбрасывается ошибка.
    """
    logger.info(f"Rent rents request for bike {req.bikeSerialNumber} by {req.login}")
    account = get_account_by_login(req.login)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    payload = {
        "frameNumber": req.bikeSerialNumber,
        "isUsedQr": True,
        "clientGeoPosition": req.clientGeoPosition,
    }
    async with get_service_session(account) as session:
        async with session.post(
            "https://pwa.velobike.ru/api/rent/rents", json=payload
        ) as resp:
            data = await resp.json()
            if resp.status == 200:
                logger.debug(f"/api/v1/rent/rents response: {data}")  # Added debug log
                if data.get("status") == "ERROR_START":
                    if data.get("failedReason") == "ACCOUNT_BLOCKED":
                        return data
                    raise HTTPException(status_code=400, detail=str(data))
                return data
            else:
                detail = await resp.text()
                logger.debug(f"/api/v1/rent/rents error: {detail}")  # Added debug log
                raise HTTPException(status_code=resp.status, detail=detail)


# ---------------------------
# Глобальная обработка ошибок
# ---------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled error: {exc}")
    return JSONResponse(status_code=500, content={"error": str(exc)})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        logger.debug(
            f"Incoming request: {request.method} {request.url} Headers: {dict(request.headers)}"
        )
        response = await call_next(request)
        return response


app.add_middleware(RequestLoggingMiddleware)
