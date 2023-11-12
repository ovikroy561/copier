import asyncio
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from telegram import Bot
import json

# Replace 'YOUR_BOT_API_TOKEN' with your actual Telegram bot API token
bot_token = '6867536640:AAGUo0VxdtlZBF__wBVMynaW-YarhFa8ujg'
chat_id = '-1002102570646'
url = "https://www.octafx.com/copy-trade/master/19846602/history/open/0/"

# Set up Chrome options for headless mode
chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--disable-gpu')
chrome_options.add_argument('--no-sandbox')

# Set up the WebDriver with increased timeout and headless mode
driver = webdriver.Chrome(options=chrome_options)
driver.get(url)

# Initialize the Telegram bot
bot = Bot(token=bot_token)

async def send_telegram_message(chat_id, message):
    await bot.send_message(chat_id=chat_id, text=message)

async def main():
    # Get the initial order count on the first run
    json_pre_element = driver.find_element(By.XPATH, "//pre[contains(text(),'\"rows\":')]")
    json_data = json.loads(json_pre_element.text)
    initial_order_count = len(json_data.get("rows", []))
    initial_orders = json_data.get("rows", [])

    while True:
        # Refresh the page to get real-time data
        driver.refresh()

        # Use an explicit wait to ensure the page is fully loaded
        wait = WebDriverWait(driver, 30)  # Increase the timeout as needed
        wait.until(EC.presence_of_element_located((By.XPATH, "//pre[contains(text(),'\"rows\":')]")))

        # Find the pre element containing the JSON data
        json_pre_element = driver.find_element(By.XPATH, "//pre[contains(text(),'\"rows\":')]")

        # Extract and parse JSON data
        json_data = json.loads(json_pre_element.text)

        # Get the current order count and details
        current_order_count = len(json_data.get("rows", []))
        current_orders = json_data.get("rows", [])

        # Check for changes in the number of orders
        if current_order_count > initial_order_count:
            # New orders added, send messages and print details for the first check
            if initial_order_count > 0:
                # Send message for the first time with details of the first new order
                new_order = current_orders[0]
                icon_text = new_order.get("icon", "")
                symbol_text = new_order.get("symbol", "")
                message = f"New Order - {icon_text.capitalize()} - {symbol_text}"
                await send_telegram_message(chat_id, message)
                print(message)
            else:
                # Print on the terminal for the first check
                print(f"Initial Order Count: {current_order_count}")

        elif current_order_count < initial_order_count:
            # Orders decreased, send generic message and print only on the first check
            if initial_order_count > 0:
                await send_telegram_message(chat_id, "Order closed")
                print("Order closed")

        # Update the initial order count and details
        initial_order_count = current_order_count
        initial_orders = current_orders

        # Wait for 1 minute before checking again
        time.sleep(2)  # Wait for 1 minute

if __name__ == '__main__':
    asyncio.run(main())

# Close the browser when done
driver.quit()
