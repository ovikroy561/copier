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
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, Filters, Updater

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
SYMBOLS = ['BTCUSD', 'AUDCHF', 'AUDJPY', 'AUDNZD', 'AUDUSD', 'CADCHF', 'CADJPY', 'CHFJPY', 'EURAUD', 'EURCAD', 'EURCHF', 'EURGBP', 'EURJPY', 'EURNZD', 'EURUSD', 'GBPAUD', 'GBPCAD', 'GBPCHF', 'GBPJPY', 'GBPNZD', 'GBPUSD', 'NOW', 'NZDCAD', 'NZDCHF', 'NZDJPY', 'NZDUSD', 'USDCAD', 'USDCHF', 'USDJPY', 'XAGUSD', 'XAUUSD']

# RISK FACTOR
RISK_FACTOR = float(os.environ.get("RISK_FACTOR"))


async def ConnectMetaTrader(trade: dict) -> None:
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
            elif trade['OrderType'] == 'Sell':
                trade['Entry'] = float(price['ask'])

        # calculates the stop loss in pips
        if trade['Symbol'] == 'XAUUSD':
            multiplier = 0.1

        elif trade['Symbol'] == 'XAGUSD':
            multiplier = 0.001

        elif str(trade['Entry']).index('.') >= 2:
            multiplier = 0.01

        else:
            multiplier = 0.0001

        stopLossPips = abs(round((trade['StopLoss'] - trade['Entry']) / multiplier))

        # calculates the position size using stop loss and RISK FACTOR
        trade['PositionSize'] = math.floor(((account_information['balance'] * trade['RiskFactor']) / stopLossPips) / 10 * 100) / 100

        # executes trade on MetaTrader account
        try:
            # executes buy market execution order
            if trade['OrderType'] == 'Buy':
                for takeProfit in trade['TP']:
                    result = await connection.create_market_buy_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['StopLoss'], takeProfit)

            # executes sell market execution order
            elif trade['OrderType'] == 'Sell':
                for takeProfit in trade['TP']:
                    result = await connection.create_market_sell_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['StopLoss'], takeProfit)

            # sends success message to user
            logger.info('\nTrade entered successfully!')
            logger.info('Result Code: {}\n'.format(result['stringCode']))

        except Exception as error:
            logger.info(f"\nTrade failed with error: {error}\n")

    except Exception as error:
        logger.error(f'Error: {error}')

    return


def HandleTradeSignal(update: Update) -> None:
    """Handles incoming trade signals.

    Arguments:
        update: update from Telegram
    """

    # Get the text message
    message_text = update.message.text

    # Define the trade signal format
    trade_format = "BUY/SELL SYMBOL\nENTRY\n"

    # Check if the message follows the trade signal format
    if trade_format.lower() in message_text.lower():
        # Parse the trade information
        trade = ParseSignal(message_text)

        # Check if the trade information is valid
        if trade:
            # Connect to MetaTrader and execute the trade
            asyncio.run(ConnectMetaTrader(trade))

        else:
            update.effective_message.reply_text("Invalid trade signal format. Please follow the format: BUY/SELL SYMBOL\nENTRY\n")

    else:
        update.effective_message.reply_text("Invalid trade signal format. Please follow the format: BUY/SELL SYMBOL\nENTRY\n")

    return


def ParseSignal(signal: str) -> dict:
    """Parses the trade signal.

    Arguments:
        signal: trading signal

    Returns:
        a dictionary that contains trade signal information
    """

    # Converts message to list of strings for parsing
    signal = signal.splitlines()
    signal = [line.rstrip() for line in signal]

    trade = {}

    # Determines the order type of the trade
    if 'Buy' in signal[0].lower():
        trade['OrderType'] = 'Buy'

    elif 'Sell' in signal[0].lower():
        trade['OrderType'] = 'Sell'

    else:
        return {}

    # Extracts symbol from trade signal
    trade['Symbol'] = (signal[0].split())[-1].upper()

    # Checks if the symbol is valid, if not, returns an empty dictionary
    if trade['Symbol'] not in SYMBOLS:
        return {}

    # Checks whether or not to convert entry to float because of market execution option ("NOW")
    if trade['OrderType'] == 'Buy' or trade['OrderType'] == 'Sell':
        trade['Entry'] = (signal[1].split())[-1]

    else:
        trade['Entry'] = float((signal[1].split())[-1])

    trade['StopLoss'] = float((signal[2].split())[-1])
    trade['TP'] = [float((signal[3].split())[-1])]

    # Checks if there's a fourth line and parses it for TP2
    if len(signal) > 4:
        trade['TP'].append(float(signal[4].split()[-1]))

    # Adds risk factor to trade
    trade['RiskFactor'] = RISK_FACTOR

    return trade


def main() -> None:
    """Runs the Telegram bot."""

    updater = Updater(TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # Command handler for handling trade signals
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, HandleTradeSignal))

    # Log all errors
    dp.add_error_handler(error)

    # Listens for incoming updates from Telegram
    updater.start_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=APP_URL + TOKEN)
    updater.idle()

    return


if __name__ == '__main__':
    main()
