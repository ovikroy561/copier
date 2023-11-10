#!/usr/bin/env python3
import logging
import math
import os
from typing import Literal

from metaapi_cloud_sdk import MetaApi
import telegram
from telegram.ext import CommandHandler, ConversationHandler, Filters, MessageHandler, Updater, CallbackContext
from prettytable import PrettyTable


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

CALCULATE, DECISION = range(2)

# MetaAPI Credentials
API_KEY = os.environ.get("API_KEY")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID")

# Telegram Credentials
TOKEN = os.environ.get("TOKEN")

# Heroku Credentials
APP_URL = os.environ.get("APP_URL")


def ParseSignal(signal: str) -> dict:
    signal = signal.splitlines()
    signal = [line.rstrip() for line in signal]

    trade = {}

    if 'Buy' in signal[1]:
        trade['OrderType'] = 'Buy'
    elif 'Sell' in signal[1]:
        trade['OrderType'] = 'Sell'
    else:
        return {}

    trade['Symbol'] = signal[1].split()[-1].upper()
    trade['Entry'] = 'NOW' if 'Now' in signal[2] else float((signal[2].split(':')[-1]).strip())
    
    tp_line = [line for line in signal if 'TP' in line]
    if tp_line:
        trade['TP'] = int(tp_line[0].split(':')[-1].replace('pips', '').strip())
    else:
        return {}

    return trade


def GetTradeInformation(update: telegram.Update, trade: dict, balance: float) -> None:
    stop_loss_pips = 20  # Set a default value for stop loss pips
    take_profit_pips = trade['TP']

    # Calculate position size using default stop loss pips
    position_size = math.floor(((balance * 0.01) / stop_loss_pips) / 10 * 100) / 100

    # Create PrettyTable object to display trade information
    table = CreateTable(trade, position_size, stop_loss_pips, take_profit_pips)

    # Send user trade information and calculated risk
    update.effective_message.reply_text(f'<pre>{table}</pre>', parse_mode=telegram.ParseMode.HTML)


def CreateTable(trade: dict, position_size: float, stop_loss_pips: int, take_profit_pips: int) -> PrettyTable:
    # Create PrettyTable object
    table = PrettyTable()

    table.title = "Trade Information"
    table.field_names = ["Key", "Value"]
    table.align["Key"] = "l"
    table.align["Value"] = "l"

    table.add_row(["Order Type", trade["OrderType"]])
    table.add_row(["Symbol", trade['Symbol']])
    table.add_row(['Entry', trade['Entry']])
    table.add_row(['Stop Loss', f'{stop_loss_pips} pips'])
    table.add_row(['Take Profit', f'{take_profit_pips} pips'])
    table.add_row(['Position Size', position_size])
    
    return table


async def ConnectMetaTrader(update: telegram.Update, trade: dict, enter_trade: bool) -> None:
    try:
        connection = await MetaApi().connect(TOKEN, ACCOUNT_ID, server=APP_URL)
        account = await connection.get_account()
        balance = account['balance']

        # Calculate trade information
        GetTradeInformation(update, trade, balance)

        if enter_trade:
            # Enter trade on MetaTrader account
            update.effective_message.reply_text("Entering trade on MetaTrader Account ... 👨🏾‍💻")

            try:
                # Execute market order based on the order type (Buy, Sell)
                if trade['OrderType'] == 'Buy':
                    await connection.create_market_buy_order(trade['Symbol'], trade['Volume'], trade['StopLoss'], trade['TakeProfit'])
                elif trade['OrderType'] == 'Sell':
                    await connection.create_market_sell_order(trade['Symbol'], trade['Volume'], trade['StopLoss'], trade['TakeProfit'])

                # Send success message to user
                update.effective_message.reply_text("Trade entered successfully! 💰")

            except Exception as error:
                logger.info(f"\nTrade failed with error: {error}\n")
                update.effective_message.reply_text(f"There was an issue 😕\n\nError Message:\n{error}")

    except Exception as error:
        logger.error(f'Error: {error}')
        update.effective_message.reply_text(f"There was an issue with the connection 😕\n\nError Message:\n{error}")


# Command Handlers
async def start(update: telegram.Update, context: CallbackContext) -> None:
    update.message.reply_text('Hi! I am your Forex Signal Parser Bot 🤖\n\nUse the /help command to see how to use me.')


async def help_command(update: telegram.Update, context: CallbackContext) -> None:
    update.message.reply_text('Here are the commands you can use:\n'
                              '/start - Start the bot\n'
                              '/help - Display this help message\n'
                              '/trade - Enter a trade based on a trading signal')


async def calculate(update: telegram.Update, context: CallbackContext) -> Literal[CALCULATE, DECISION]:
    trade = ParseSignal(update.message.text)

    if len(trade) == 0:
        update.effective_message.reply_text("You've entered an invalid trade 😕\n\nPlease try again using the /trade command.")
        return ConversationHandler.END

    connection = await MetaApi().connect(TOKEN, ACCOUNT_ID, server=APP_URL)
    account = await connection.get_account()
    balance = account['balance']

    GetTradeInformation(update, trade, balance)

    keyboard = [['Yes', 'No']]
    reply_markup = telegram.ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("Would you like to enter this trade?", reply_markup=reply_markup)

    return DECISION


async def decision(update: telegram.Update, context: CallbackContext) -> Literal[CALCULATE, DECISION]:
    decision = update.message.text.lower()
    if decision == 'yes':
        trade = ParseSignal(update.message.text)
        await ConnectMetaTrader(update, trade, True)
    elif decision == 'no':
        update.message.reply_text('Trade entry declined.')
    else:
        update.message.reply_text('Invalid decision. Please use the provided buttons to make a decision.')

    return ConversationHandler.END


def main() -> None:
    updater = Updater(TOKEN, use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", calculate)],
        states={
            CALCULATE: [MessageHandler(Filters.text & ~Filters.command, calculate)],
            DECISION: [MessageHandler(Filters.text & ~Filters.command, decision)]
        },
        fallbacks=[]
    )

    dp.add_handler(conv_handler)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
