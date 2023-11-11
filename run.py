from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from MetaTrader4 import MetaTrader4

# Replace with your actual Telegram bot token
TELEGRAM_BOT_TOKEN = "6709486839:AAFVlvHaiQwbdjgEbxvAc5qo7_lcXuxXiVE"

# Replace with your MetaTrader 4 account details
MT4_SERVER = "OctaFX-Demo"
MT4_LOGIN = "55057242"
MT4_PASSWORD = "myPYmYsE"

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Bot connected to MetaTrader 4 successfully!')

def main() -> None:
    updater = Updater(token=TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher

    # Add a command handler for the /start command
    dispatcher.add_handler(CommandHandler("start", start))

    # Start the bot
    updater.start_polling()

    # Connect to MetaTrader 4
    mt4 = MetaTrader4(MT4_SERVER, MT4_LOGIN, MT4_PASSWORD)

    # Check if the connection to MetaTrader 4 is successful
    if mt4.connected:
        print("Connected to MetaTrader 4 successfully!")
    else:
        print("Failed to connect to MetaTrader 4.")

    # Run the bot until you send a signal to stop
    updater.idle()

if __name__ == '__main__':
    main()
