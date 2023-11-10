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
from telegram.ext import MessageHandler, Filters, Updater, CallbackContext

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

# allowed FX symbols
SYMBOLS = ['AUDCAD', 'AUDCHF', 'AUDJPY', 'AUDNZD', 'AUDUSD', 'CADCHF', 'CADJPY', 'CHFJPY', 'EURAUD', 'EURCAD', 'EURCHF', 'EURGBP', 'EURJPY', 'EURNZD', 'EURUSD', 'GBPAUD', 'GBPCAD', 'GBPCHF', 'GBPJPY', 'GBPNZD', 'GBPUSD', 'NOW', 'NZDCAD', 'NZDCHF', 'NZDJPY', 'NZDUSD', 'USDCAD', 'USDCHF', 'USDJPY', 'XAGUSD', 'XAUUSD']

# RISK FACTOR
RISK_FACTOR = float(os.environ.get("RISK_FACTOR"))

# Helper Functions
def ParseSignal(signal: str) -> dict:
    """Starts the process of parsing the signal and entering a trade on the MetaTrader account.

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
    if 'BUY' in signal[0].upper():
        trade['OrderType'] = 'Buy'
    elif 'SELL' in signal[0].upper():
        trade['OrderType'] = 'Sell'
    else:
        raise Exception('Invalid trade')

    # extracts symbol from trade signal
    trade['Symbol'] = signal[1].upper()

    # checks if the symbol is valid, if not, returns an empty dictionary
    if trade['Symbol'] not in SYMBOLS:
        raise Exception('Invalid trade')

    # checks if the entry is set to 'NOW' for market execution
    if 'Entry NOW' in signal[2].upper():
        trade['Entry'] = 'NOW'
    else:
        raise Exception('Invalid trade')

    # Set fixed take profit(s) in pips
    trade['TP'] = [50]

    return trade

async def ConnectMetaTrader(trade: dict):
    """Attempts connection to MetaAPI and MetaTrader to place trade.

    Arguments:
        trade: dictionary that stores trade information
    """

    # creates connection to MetaAPI
    api = MetaApi(API_KEY)

    try:
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        initial_state = account.state
        deployed_states = ['DEPLOYING', 'DEPLOYED']

        if initial_state not in deployed_states:
            #  wait until account is deployed and connected to broker
            logger.info('Deploying account')
            await account.deploy()

        logger.info('Waiting for API server to connect to broker ...')
        await account.wait_connected()

        # connect to MetaApi API
        connection = account.get_rpc_connection()
        await connection.connect()

        # wait until terminal state synchronized to the local state
        logger.info('Waiting for SDK to synchronize to terminal state ...')
        await connection.wait_synchronized()

        # obtains account information from MetaTrader server
        account_information = await connection.get_account_information()

        # checks if the order is a market execution to get the current price of symbol
        if trade['Entry'] == 'NOW':
            price = await connection.get_symbol_price(symbol=trade['Symbol'])

            # uses bid price if the order type is a buy
            if trade['OrderType'] == 'Buy':
                trade['Entry'] = float(price['bid'])

            # uses ask price if the order type is a sell
            if trade['OrderType'] == 'Sell':
                trade['Entry'] = float(price['ask'])

        # calculates the position size using the fixed lot size and RISK FACTOR
        trade['PositionSize'] = math.floor(((account_information['balance'] * RISK_FACTOR) / 50) / 10 * 100) / 100

        # enters trade on to MetaTrader account
        logger.info("Entering trade on MetaTrader Account ... 👨🏾‍💻")
        await connection.create_limit_order(
            symbol=trade['Symbol'],
            order_type=trade['OrderType'],
            volume=trade['PositionSize'],
            price=trade['Entry'],
            stop_loss=trade['Entry'] - 50,  # stop loss set to 50 pips
            take_profit=trade['Entry'] + 50  # take profit set to 50 pips
        )

        logger.info('Trade executed successfully! 💹')

    except Exception as err:
        logger.exception('Failed to connect to MetaTrader terminal due to ' + str(err))

async def ExecuteTrade(signal: str):
    """Executes the trading logic based on the given signal.

    Arguments:
        signal: trading signal
    """
    try:
        # parses the signal to get trade information
        trade = ParseSignal(signal)

        # connects to MetaTrader and executes the trade
        await ConnectMetaTrader(trade)

    except Exception as err:
        logger.exception('Failed to execute trade due to ' + str(err))

def HandleText(update: Update, context: CallbackContext) -> None:
    """Handles incoming text messages.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """
    # retrieves the user's message
    message_text = update.message.text

    # checks if the message is in the expected format
    if 'BUY' in message_text.upper() or 'SELL' in message_text.upper():
        if 'NOW' in message_text.upper():
            # executes the trade based on the message
            asyncio.run(ExecuteTrade(message_text))
            update.message.reply_text("Trade executed successfully! 💹")
        else:
            update.message.reply_text("Invalid trade. Please use the format: BUY/SELL SYMBOL\nEntry NOW")

# sets up the bot with the given token
updater = Updater(TOKEN, use_context=True)

# gets the dispatcher to register handlers
dp = updater.dispatcher

# registers the text message handler
dp.add_handler(MessageHandler(Filters.TEXT & ~Filters.COMMAND, HandleText))

# starts the bot
updater.start_polling()

# Run the bot until the user presses Ctrl-C or the process receives SIGINT,
# SIGTERM or SIGABRT. This should be used most of the time, since
# start_polling() is non-blocking and will stop the bot gracefully.
updater.idle()
