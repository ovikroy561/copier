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
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater

# MetaAPI Credentials
API_KEY = os.environ.get("API_KEY")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID")

# Telegram Credentials
TOKEN = os.environ.get("TOKEN")
TELEGRAM_USER = os.environ.get("TELEGRAM_USER")

# Heroku Credentials
APP_URL = os.environ.get("APP_URL")
PORT = int(os.environ.get('PORT', '8443'))

# Enables logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# allowed FX symbols
SYMBOLS = ['BTCUSD', 'AUDCHF', 'AUDJPY', 'AUDNZD', 'AUDUSD', 'CADCHF', 'CADJPY', 'CHFJPY', 'EURAUD', 'EURCAD', 'EURCHF', 'EURGBP', 'EURJPY', 'EURNZD', 'EURUSD', 'GBPAUD', 'GBPCAD', 'GBPCHF', 'GBPJPY', 'GBPNZD', 'GBPUSD', 'NOW', 'NZDCAD', 'NZDCHF', 'NZDJPY', 'NZDUSD', 'USDCAD', 'USDCHF', 'USDJPY', 'XAGUSD', 'XAUUSD']

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
    if 'BUY' in signal[0].upper():
        trade['OrderType'] = 'Buy'
    elif 'SELL' in signal[0].upper():
        trade['OrderType'] = 'Sell'
    else:
        return {}

    # extracts symbol from trade signal
    trade['Symbol'] = (signal[0].split())[-1].upper()

    # checks wheter or not to convert entry to float because of market exectution option ("NOW")
    if signal[1].upper() == 'NOW':
        trade['Entry'] = 'NOW'
    else:
        trade['Entry'] = float((signal[1].split())[-1])

    trade['StopLoss'] = float((signal[2].split())[-1])
    trade['TP'] = [float((signal[3].split())[-1])]

    # checks if there's a fourth line and parses it for TP2
    if len(signal) > 4:
        trade['TP'].append(float(signal[4].split()[-1]))

    # adds risk factor to trade
    trade['RiskFactor'] = RISK_FACTOR

    return trade

async def ConnectMetaTrader(update: Update, trade: dict, enterTrade: bool):
    """Attempts connection to MetaAPI and MetaTrader to place trade.

    Arguments:
        update: update from Telegram
        trade: dictionary that stores trade information

    Returns:
        A coroutine that confirms that the connection to MetaAPI/MetaTrader and trade placement were successful
    """

    # creates connection to MetaAPI
    api = MetaApi(API_KEY)

    try:
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        initial_state = account.state
        deployed_states = ['DEPLOYING', 'DEPLOYED']

        if initial_state not in deployed_states:
            # wait until account is deployed and connected to broker
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

        update.effective_message.reply_text("Successfully connected to MetaTrader!\nCalculating trade risk ... 🤔")

        # checks if the order is a market execution to get the current price of symbol
        if trade['Entry'] == 'NOW':
            price = await connection.get_symbol_price(symbol=trade['Symbol'])

            # uses bid price if the order type is a buy
            if trade['OrderType'] == 'Buy':
                trade['Entry'] = float(price['bid'])

            # uses ask price if the order type is a sell
            if trade['OrderType'] == 'Sell':
                trade['Entry'] = float(price['ask'])

        # prints success message to console
        logger.info('\nTrade entered successfully!')
            
        # checks if the user has indicated to enter trade
        if enterTrade:

            # enters trade on to MetaTrader account
            update.effective_message.reply_text("Entering trade on MetaTrader Account ... 👨🏾‍💻")

            try:
                # executes buy market execution order
                if trade['OrderType'] == 'Buy':
                    for takeProfit in trade['TP']:
                        result = await connection.create_market_buy_order(trade['Symbol'], 1, trade['StopLoss'], takeProfit)

                # executes sell market execution order
                elif trade['OrderType'] == 'Sell':
                    for takeProfit in trade['TP']:
                        result = await connection.create_market_sell_order(trade['Symbol'], 1, trade['StopLoss'], takeProfit)
                
                # sends success message to user
                update.effective_message.reply_text("Trade entered successfully! 💰")
                
                # prints success message to console
                logger.info('Result Code: {}\n'.format(result['stringCode']))
            
            except Exception as error:
                logger.info(f"\nTrade failed with error: {error}\n")
                update.effective_message.reply_text(f"There was an issue 😕\n\nError Message:\n{error}")
    
    except Exception as error:
        logger.error(f'Error: {error}')
        update.effective_message.reply_text(f"There was an issue with the connection 😕\n\nError Message:\n{error}")
    
    return

# Command Handlers
def PlaceTrade(update: Update, context: CallbackContext) -> None:
    """Parses trade and places on MetaTrader account.   
    
    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    try: 
        # parses signal from Telegram message
        trade = ParseSignal(update.effective_message.text)
        
        # checks if there was an issue with parsing the trade
        if not trade:
            raise Exception('Invalid Trade')

        update.effective_message.reply_text("Trade Successfully Parsed! 🥳\nConnecting to MetaTrader ... (May take a while) ⏰")

        # attempts connection to MetaTrader and places trade
        asyncio.run(ConnectMetaTrader(update, trade, True))
    
    except Exception as error:
        logger.error(f'Error: {error}')
        errorMessage = f"There was an error parsing this trade 😕\n\nError: {error}\n\nPlease re-enter trade with this format:\n\nBUY/SELL SYMBOL\nEntry \nSL \nTP \n\nOr use the /cancel to command to cancel this action."
        update.effective_message.reply_text(errorMessage)

    return


def main() -> None:
    """Runs the Telegram bot."""

    updater = Updater(TOKEN, use_context=True)

    # get the dispatcher to register handlers
    dp = updater.dispatcher

    # message handler
    dp.add_handler(CommandHandler("start", welcome))

    # help command handler
    dp.add_handler(CommandHandler("help", help))

    # command handler for /trade
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, PlaceTrade))

    # command handler for /cancel
    dp.add_handler(CommandHandler("cancel", cancel))

    # log all errors
    dp.add_error_handler(error)
    
    # listens for incoming updates from Telegram
    updater.start_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=APP_URL + TOKEN)
    updater.idle()

    return


if __name__ == '__main__':
    main()
