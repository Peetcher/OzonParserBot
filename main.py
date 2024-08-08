import re
import json
import time
import logging
from datetime import datetime
from config import OZON_BOT_TOKEN, LOGGING_CHAT_ID
from curl_cffi import requests
from bs4 import BeautifulSoup
from telegram import Update, Bot
from telegram.ext import CommandHandler, MessageHandler, CallbackContext, filters, Application
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium_stealth import stealth


TOKEN = OZON_BOT_TOKEN
bot = Bot(token=TOKEN)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OzonProductParser:
    OZON_URL_PATTERN = re.compile(r'https?://(www\.)?ozon\.ru/.*')
    OZON_PRODUCT_URL_PATTERN = re.compile(r'https?://(www\.)?ozon\.ru/product/[\w-]+-(\d+)/?.*')

    def __init__(self):
        chrome_options = Options()
        self.driver = webdriver.Chrome(options=chrome_options)

        stealth(self.driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True)

        self.driver.maximize_window()

    def is_ozon_url(self, url: str) -> bool:
        return bool(self.OZON_URL_PATTERN.match(url))

    def is_ozon_product_url(self, url: str) -> bool:
        return bool(self.OZON_PRODUCT_URL_PATTERN.match(url))

    async def fetch_ozon_product_info(self, url: str, user_id: int):
        #self.driver.get(url)

        try:
            product_info = await self.get_product_info(url, user_id)
            return {
                "full_name": product_info['full_name'],
                "price": product_info['price'],
                "description": product_info.get('description', 'Описание отсутствует'),
            }
        except Exception as e:
            await self.log_to_chanel(user_id, f"Ошибка при извлечении информации о товаре: {url} \nТекст ошибки: {e}")
            return None

    async def get_product_info(self, product_url: str, user_id: int) -> dict:

        session = requests.Session()
        await self.log_to_chanel(user_id, f"старт парсинга ссылки: {product_url}")
        raw_data = session.get("https://www.ozon.ru/api/composer-api.bx/page/json/v2?url=" + product_url)
        await self.log_to_chanel(user_id, f"статус ответа {raw_data.status_code}")
        json_data = json.loads(raw_data.content.decode())

        full_name = json.loads(json_data["seo"]["script"][0]["innerHTML"])['name']

        product_info = {
            "product_id": None,
            "full_name": full_name,
            "description": None,
            "price": None,
            "rating": None
        }

        # Проверка на модальное окно для товаров 18+
        if json_data["layout"][0]["component"] == "userAdultModal":
            product_info["description"] = "Товар для лиц старше 18 лет"
            await self.log_to_chanel(user_id, "Товар для лиц старше 18 лет")
            return product_info

        product_info["description"] = json.loads(json_data["seo"]["script"][0]["innerHTML"])["description"]
        product_info["price"] = json.loads(json_data["seo"]["script"][0]["innerHTML"])["offers"]["price"] + " " + \
                                json.loads(json_data["seo"]["script"][0]["innerHTML"])["offers"]["priceCurrency"]
        product_info["rating"] = json.loads(json_data["seo"]["script"][0]["innerHTML"])["aggregateRating"][
            "ratingValue"]
        product_info["product_id"] = json.loads(json_data["seo"]["script"][0]["innerHTML"])["sku"]
        await self.log_to_chanel(user_id, f"Информация о товаре успешно получена")

        return product_info

    async def log_to_chanel(self, user_id: int, log_message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"User ID: {user_id}\nTime: {timestamp}\nLog: {log_message}"
        await bot.send_message(chat_id=LOGGING_CHAT_ID, text=full_message)

    def close(self):
        self.driver.quit()


async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Привет! Отправь мне ссылку на товар с Ozon, и я предоставлю информацию о нем.")


async def check_url(parser: OzonProductParser, url: str, update: Update) -> bool:
    if parser.is_ozon_url(url):
        if parser.is_ozon_product_url(url):
            return True
        else:
            await update.message.reply_text("Мне нужна ссылка на конкретный товар.")
            return False
    else:
        await update.message.reply_text("Это не ссылка товара Ozon. Пожалуйста, отправьте корректную ссылку.")
        return False


async def handle_message(update: Update, context: CallbackContext, parser: OzonProductParser) -> None:

    message = update.message.text
    user_id = update.message.from_user.id

    await parser.log_to_chanel(user_id, f"получено сообщение: {message}")

    if await check_url(parser, message, update):
        product_info = await parser.fetch_ozon_product_info(message, user_id)
        if product_info:
            await update.message.reply_text(
                f"Товар: {product_info['full_name']}\nЦена: {product_info['price']}"
            )
            await parser.log_to_chanel(user_id, f"отправлено сообщение: Товар: {product_info['full_name']}\nЦена: {product_info['price']}")
        else:
            await update.message.reply_text("Не удалось получить информацию о товаре.")
    else:
        await parser.log_to_chanel(user_id, "Ссылка не прошла проверку")
    parser.close()


def main() -> None:
    parser = OzonProductParser()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                           lambda update, context: handle_message(update, context, parser)))

    application.run_polling(1.0)

    parser.close()


if __name__ == '__main__':
    main()
