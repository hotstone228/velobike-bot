import logging
import os

# Настройка уровня логирования через переменную окружения или по умолчанию
import yaml

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

# Load secrets from secrets.yaml
with open("secrets.yaml", "r", encoding="utf-8") as f:
    secrets = yaml.safe_load(f)

BOT_TOKEN = os.getenv("BOT_TOKEN", secrets.get("bot_token", ""))
API_BASE_URL = secrets.get(
    "api_base_url", "http://localhost:8000/api/v1"
)  # URL вашего API-сервера
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Параметры подключения к БД PostgreSQL
# Формат: postgresql://<user>:<password>@<host>:<port>/<database>
DATABASE_URL = os.getenv("DATABASE_URL", secrets.get("database_url", ""))

# Глобальные заголовки для запросов к сервису
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7,zh-CN;q=0.6,zh;q=0.5",
    "app-version": "1.55.108",
    "Connection": "keep-alive",
    "Host": "pwa.velobike.ru",
    "initiator": "pwa_app",
    "Referer": "https://pwa.velobike.ru/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "source": "pwa-client",
}
