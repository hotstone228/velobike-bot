import time
import requests

# patchright here!
from patchright.sync_api import sync_playwright
from config import HEADERS
from database import get_all_accounts, update_account, logger


def wait_for_page_load(page, timeout=20000):
    """
    Ждет полной загрузки страницы, используя метод wait_for_load_state.
    Дополнительная задержка учитывает редиректы.
    """
    try:
        page.wait_for_load_state("load", timeout=timeout)
        time.sleep(2)
        return True
    except Exception as e:
        logger.error(f"Ошибка ожидания загрузки страницы: {e}")
        return False


def get_qrator_cookie(page):
    """
    Извлекает cookie с именем 'qrator_jsid' из Playwright.
    """
    cookies = page.context.cookies()
    for cookie in cookies:
        if cookie["name"] == "qrator_jsid":
            logger.info(f"Получен cookie qrator_jsid: {cookie['value']}")
            return cookie["value"]
    logger.error("Cookie 'qrator_jsid' не найден!")
    return None


def authenticate_account(login, password, cookie_value):
    """
    Выполняет POST-запрос для аутентификации с использованием requests,
    устанавливая переданный cookie для домена pwa.velobike.ru.
    Возвращает token при успешном ответе, иначе None.
    """
    session_requests = requests.Session()
    session_requests.cookies.set("qrator_jsid", cookie_value, domain="pwa.velobike.ru")
    payload = {"user": login, "password": password}

    try:
        response = session_requests.post(
            "https://pwa.velobike.ru/api/api-auth/authenticate",
            json=payload,
            headers=HEADERS,
        )
        if response.status_code == 200:
            data = response.json()
            token = data.get("token")
            if token:
                logger.info(f"Успешная аутентификация для {login}. Получен token.")
                return token
            else:
                logger.error(f"Для {login} token не найден в ответе: {data}")
        else:
            logger.error(
                f"Ошибка аутентификации для {login}. Код: {response.status_code}. Ответ: {response.text}"
            )
    except Exception as e:
        logger.error(f"Исключение при аутентификации для {login}: {e}")
    return None


def handle_request(route, request):
    print("Headers:", request.headers)
    route.continue_()


def main():
    # Получаем список всех аккаунтов из базы данных
    accounts = get_all_accounts()
    logger.info(f"Найдено {len(accounts)} аккаунтов для обработки.")

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir="chrome", headless=False, no_viewport=True, channel="chrome"
        )
        page = browser.new_page()
        logger.info("Playwright браузер запущен.")

        for account in accounts:
            logger.info(f"Обработка аккаунта: {account.login}")
            try:
                page.goto("https://pwa.velobike.ru", timeout=30000)

                if not wait_for_page_load(page):
                    logger.error(
                        f"Страница не загрузилась для {account.login}. Пропускаем аккаунт."
                    )
                    continue

                cookie_value = get_qrator_cookie(page)
                if not cookie_value:
                    logger.error(
                        f"Не удалось получить cookie для {account.login}. Пропускаем аккаунт."
                    )
                    continue

                token = authenticate_account(
                    account.login, account.password, cookie_value
                )
                if token:
                    update_account(account.login, cookie=cookie_value, token=token)
                    logger.info(f"Данные успешно обновлены для {account.login}.")
                else:
                    logger.error(f"Не удалось получить token для {account.login}.")
            except Exception as e:
                logger.error(f"Ошибка при обработке аккаунта {account.login}: {e}")
            finally:
                browser.clear_cookies()
                logger.info("Очистка куки браузера выполнена для следующего аккаунта.")

        browser.close()
        logger.info("Обработка всех аккаунтов завершена.")


if __name__ == "__main__":
    main()
