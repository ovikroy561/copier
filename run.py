#!/usr/bin/env python3
import asyncio
import logging
import math
import os

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

from metaapi_cloud_sdk import MetaApi
from prettytable import PrettyTable
from telegram import ParseMode, Update
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater, ConversationHandler, CallbackContext

# MetaAPI Credentials
API_KEY = os.environ.get("API_KEY")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID")

# Telegram Credentials
TOKEN = os.environ.get("TOKEN")
TELEGRAM_USER = os.environ.get("TELEGRAM_USER")

# Heroku Credentials
APP_URL = os.environ.get("APP_URL")

# Port number for Telegram bot web hook
PORT = int(os.environ.get('PORT', '8443'))

# Enables logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# possibles states for conversation handler
CALCULATE, TRADE, DECISION = range(3)

# allowed FX symbols
SYMBOLS = ['BTCUSD', 'AUDCHF', 'AUDJPY', 'AUDNZD', 'AUDUSD', 'CADCHF', 'CADJPY', 'CHFJPY', 'EURAUD', 'EURCAD', 'EURCHF',
           'EURGBP', 'EURJPY', 'EURNZD', 'EURUSD', 'GBPAUD', 'GBPCAD', 'GBPCHF', 'GBPJPY', 'GBPNZD', 'GBPUSD', 'NOW',
           'NZDCAD', 'NZDCHF', 'NZDJPY', 'NZDUSD', 'USDCAD', 'USDCHF', 'USDJPY', 'XAGUSD', 'XAUUSD']

# RISK FACTOR
RISK_FACTOR = float(os.environ.get("RISK_FACTOR"))


# Helper Functions
def ParseSignal(signal: str) -> dict:
    """Starts process of parsing signal and entering trade on MetaTrader account.

    Arguments:
        signal: trading signal

    Returns:
        a dictionary that contains trade signal information
    """

    # converts message to list of strings for parsing
    signal = signal.splitlines()
    signal = [line.rstrip() for line in signal]

    trade = {}

    # determines the order type of the trade
    if 'Buy Limit'.lower() in signal[0].lower():
        trade['OrderType'] = 'Buy Limit'
    elif 'Sell Limit'.lower() in signal[0].lower():
        trade['OrderType'] = 'Sell Limit'
    elif 'Buy Stop'.lower() in signal[0].lower():
        trade['OrderType'] = 'Buy Stop'
    elif 'Sell Stop'.lower() in signal[0].lower():
        trade['OrderType'] = 'Sell Stop'
    elif 'Buy'.lower() in signal[0].lower():
        trade['OrderType'] = 'Buy'
    elif 'Sell'.lower() in signal[0].lower():
        trade['OrderType'] = 'Sell'
    else:
        return {}  # returns an empty dictionary if an invalid order type was given

    # extracts symbol from trade signal
    trade['Symbol'] = (signal[0].split())[-1].upper()

    # checks if the symbol is valid, if not, returns an empty dictionary
    if trade['Symbol'] not in SYMBOLS:
        return {}

    # checks whether or not to convert entry to float because of market execution option ("NOW")
    if trade['OrderType'] == 'Buy' or trade['OrderType'] == 'Sell':
        trade['Entry'] = (signal[1].split())[-1]
    else:
        trade['Entry'] = float((signal[1].split())[-1])

    trade['StopLoss'] = float((signal[2].split())[-1])
    trade['TP'] = [float((signal[3].split())[-1])]

    # checks if there's a fourth line and parses it for TP2
    if len(signal) > 4:
        trade['TP'].append(float(signal[4].split()[-1])

    # adds risk factor to trade
    trade['RiskFactor'] = RISK_FACTOR

    return trade


def GetTradeInformation(update: Update, trade: dict, balance: float) -> None:
    """Calculates information from given trade including stop loss and take profit in pips, position size, and potential loss/profit.

    Arguments:
        update: update from Telegram
        trade: dictionary that stores trade information
        balance: current balance of the MetaTrader account
    """

    # calculates the stop loss in pips
    if trade['Symbol'] == 'XAUUSD':
        multiplier = 0.1
    elif trade['Symbol'] == 'XAGUSD':
        multiplier = 0.001
    elif str(trade['Entry']).index('.') >= 2:
        multiplier = 0.01
    else:
        multiplier = 0.0001

    # calculates the stop loss in pips
    stopLossPips = abs(round((trade['StopLoss'] - trade['Entry']) / multiplier))

    # calculates the position size using stop loss and RISK FACTOR
    trade['PositionSize'] = math.floor(((balance * trade['RiskFactor']) / stopLossPips) / 10 * 100) / 100

    # calculates the take profit(s) in pips
    takeProfitPips = [50]  # Auto-set TP to 50 pips
    trade['TP'] = takeProfitPips

    # creates table with trade information
    table = CreateTable(trade, balance, stopLossPips, takeProfitPips)

    # sends user trade information and calculated risk
    update.effective_message.reply_text(f'<pre>{table}</pre>', parse_mode=ParseMode.HTML)

    return


def CreateTable(trade: dict, balance: float, stopLossPips: int, takeProfitPips: int) -> PrettyTable:
    """Creates PrettyTable object to display trade information to user.

    Arguments:
        trade: dictionary that stores trade information
        balance: current balance of the MetaTrader account
        stopLossPips: the difference in pips from stop loss price to entry price

    Returns:
        a Pretty Table object that contains trade information
    """

    # creates prettytable object
    table = PrettyTable()

    table.title = "Trade Information"
    table.field_names = ["Key", "Value"]
    table.align["Key"] = "l"
    table.align["Value"] = "l"

    table.add_row([trade["OrderType"], trade["Symbol"]])
    table.add_row(['Entry\n', trade['Entry']])

    table.add_row(['Stop Loss', '{} pips'.format(stopLossPips)])

    for count, takeProfit in enumerate(takeProfitPips):
        table.add_row([f'TP {count + 1}', f'{takeProfit} pips'])

    table.add_row(['\nRisk Factor', '\n{:,.0f} %'.format(trade['RiskFactor'] * 100)])
    table.add_row(['Balance', '{:,.2f} USD'.format(balance)])
    table.add_row(['Position Size', '{:,.2f} lots'.format(trade['PositionSize'])])

    return table


async def ConnectMetaTrader(update: Update, trade: dict, auto_trade: bool) -> None:
    """Connects to MetaTrader account and executes trade.

    Arguments:
        update: update from Telegram
        trade: dictionary that stores trade information
        auto_trade: whether or not the trade is executed automatically (without asking user for confirmation)
    """

    # initializes connection to MetaApi
    api = MetaApi(token=API_KEY, account_id=ACCOUNT_ID)

    # retrieves MetaTrader account information
    account = await api.metatrader.get_account()
    balance = account['balance']

    # retrieves MetaTrader connection information
    connection = await api.metatrader.get_account_connection('MetaApi')

    # attempts connection to MetaTrader and places trade
    await asyncio.gather(
        ConnectMetaTrader(update, context.user_data['trade'], True),
        ConnectMetaTrader(update, context.user_data['trade'], False)
    )

    # removes trade from user context data
    context.user_data['trade'] = None

    return ConversationHandler.END


# Callback Functions
def start(update: Update, context: CallbackContext) -> int:
    """Starts conversation with user and asks for trading signal.

    Returns:
        CALCULATE: next state for conversation handler
    """

    # sends welcome message to user
    update.message.reply_text("Welcome to the Trade Calculator Bot!\n\n"
                              "Please enter your trading signal in the following format:\n\n"
                              "<code>Order Type\nSymbol\nEntry\nStop Loss\nTake Profit</code>\n\n"
                              "For example:\n"
                              "<code>Buy\nEURUSD\n1.2000\n1.1950\n1.2050</code>\n\n"
                              "If you need help, type /help.")

    return CALCULATE


def help_command(update: Update, context: CallbackContext) -> None:
    """Sends help message to user.

    Arguments:
        update: update from Telegram
        context: context from CallbackContext
    """

    update.message.reply_text("To use this bot, follow these steps:\n\n"
                              "1. Enter your trading signal in the following format:\n\n"
                              "<code>Order Type\nSymbol\nEntry\nStop Loss\nTake Profit</code>\n\n"
                              "2. The bot will calculate the risk and display the trade information.\n\n"
                              "3. Confirm the trade to execute it on MetaTrader.\n\n"
                              "For example:\n"
                              "<code>Buy\nEURUSD\n1.2000\n1.1950\n1.2050</code>\n\n"
                              "If you need further assistance, type /help.")

    return


def calculate(update: Update, context: CallbackContext) -> int:
    """Parses trading signal and calculates trade information.

    Arguments:
        update: update from Telegram
        context: context from CallbackContext

    Returns:
        TRADE: next state for conversation handler
    """

    # parses trading signal
    trade = ParseSignal(update.message.text)

    # checks if signal was parsed successfully
    if trade:
        # saves trade in user context data
        context.user_data['trade'] = trade

        # sends message to user asking if they would like to enter the trade
        GetTradeInformation(update, trade, context.user_data['balance'])

        # asks if user if they would like to enter or decline trade
        update.effective_message.reply_text("Would you like to enter this trade?\nTo enter, select: /yes\nTo decline, select: /no")

        return DECISION
    else:
        # sends error message to user if signal was not parsed successfully
        update.message.reply_text("Error: Trading signal could not be parsed.\n\n"
                                  "Please make sure the signal is in the correct format and try again.\n"
                                  "If you need help, type /help.")

        return CALCULATE


def yes(update: Update, context: CallbackContext) -> int:
    """Connects to MetaTrader and executes trade.

    Arguments:
        update: update from Telegram
        context: context from CallbackContext

    Returns:
        ConversationHandler.END: ends conversation
    """

    # retrieves MetaTrader account information
    account = api.metatrader.get_account().result()
    balance = account['balance']

    # retrieves trade information from user context data
    trade = context.user_data['trade']

    # calculates information for user
    GetTradeInformation(update, trade, balance)

    # asks if user if they would like to enter or decline trade
    update.effective_message.reply_text("Trade has been executed on MetaTrader.\n"
                                        "If you have any additional trades, type /start.\n"
                                        "If you're done, type /stop.")

    return ConversationHandler.END


def no(update: Update, context: CallbackContext) -> int:
    """Ends conversation with user.

    Arguments:
        update: update from Telegram
        context: context from CallbackContext

    Returns:
        ConversationHandler.END: ends conversation
    """

    # removes trade from user context data
    context.user_data['trade'] = None

    # sends message to user indicating that the trade has been declined
    update.message.reply_text("Trade has been declined.\n"
                              "If you have any additional trades, type /start.\n"
                              "If you're done, type /stop.")

    return ConversationHandler.END


def error(update: Update, context: CallbackContext) -> None:
    """Logs errors and sends error message to user.

    Arguments:
        update: update from Telegram
        context: context from CallbackContext
    """

    # logs errors
    logger.warning('Update "%s" caused error "%s"', update, context.error)

    # sends error message to user
    update.message.reply_text('An error occurred. Please try again later.')


async def main():
    # creates updater and dispatcher
    updater = Updater(TOKEN, use_context=True)

    # gets the dispatcher to register handlers
    dp = updater.dispatcher

    # creates conversation handler
    trade_calculator_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CALCULATE: [MessageHandler(Filters.text & ~Filters.command, calculate)],
            DECISION: [CommandHandler('yes', yes), CommandHandler('no', no)],
        },
        fallbacks=[],
        name="trade_calculator_handler",
    )

    # registers handlers with dispatcher
    dp.add_handler(trade_calculator_handler)
    dp.add_handler(CommandHandler('help', help_command))
    dp.add_error_handler(error)

    # starts the Bot
    await updater.start_webhook(listen="0.0.0.0",
                                port=PORT,
                                url_path=TOKEN)
    updater.bot.set_webhook(url=f"{APP_URL}/{TOKEN}")

    # runs the bot until you send a signal to stop it
    updater.idle()


if __name__ == '__main__':
    asyncio.run(main())
