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
PORT = int(os.environ.get('PORT', '443'))

# Enables logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# possibles states for conversation handler
CALCULATE, DECISION = range(2)

# allowed FX symbols
SYMBOLS = ['AUDCAD', 'AUDCHF', 'AUDJPY', 'AUDNZD', 'AUDUSD', 'CADCHF', 'CADJPY', 'CHFJPY', 'EURAUD', 'EURCAD', 'EURCHF', 'EURGBP', 'EURJPY', 'EURNZD', 'EURUSD', 'GBPAUD', 'GBPCAD', 'GBPCHF', 'GBPJPY', 'GBPNZD', 'GBPUSD', 'NOW', 'NZDCAD', 'NZDCHF', 'NZDJPY', 'NZDUSD', 'USDCAD', 'USDCHF', 'USDJPY', 'XAGUSD', 'XAUUSD']

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
    if('Buy'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Buy'
    
    elif('Sell'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Sell'
    
    # returns an empty dictionary if an invalid order type was given
    else:
        return {}

    # extracts symbol from trade signal
    trade['Symbol'] = (signal[0].split())[-1].upper()
    
    # checks if the symbol is valid, if not, returns an empty dictionary
    if(trade['Symbol'] not in SYMBOLS):
        return {}

    # checks whether or not to convert entry to float because of market execution option ("NOW")
    if(trade['OrderType'] == 'Buy' or trade['OrderType'] == 'Sell'):
        trade['Entry'] = 'NOW'
    
    # calculates risk factor
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

        update.effective_message.reply_text("Successfully connected to MetaTrader!\nCalculating trade risk ... 🤔")

        # checks if the order is a market execution to get the current price of symbol
        if(trade['Entry'] == 'NOW'):
            price = await connection.get_symbol_price(symbol=trade['Symbol'])

            # uses bid price if the order type is a buy
            if(trade['OrderType'] == 'Buy'):
                trade['Entry'] = float(price['bid'])

            # uses ask price if the order type is a sell
            if(trade['OrderType'] == 'Sell'):
                trade['Entry'] = float(price['ask'])

        # produces a table with trade information
        GetTradeInformation(update, trade, account.state['balance'])
            
        # checks if the user has indicated to enter trade
        if(enterTrade == True):

            # enters trade on to MetaTrader account
            update.effective_message.reply_text("Entering trade on MetaTrader Account ... 👨🏾‍💻")

            try:
                # executes buy market execution order
                if(trade['OrderType'] == 'Buy'):
                    result = await connection.create_market_buy_order(trade['Symbol'], trade['PositionSize'], None, trade['TP'][0])

                # executes sell market execution order
                elif(trade['OrderType'] == 'Sell'):
                    result = await connection.create_market_sell_order(trade['Symbol'], trade['PositionSize'], None, trade['TP'][0])
                
                # sends success message to user
                update.effective_message.reply_text("Trade entered successfully! 💰")
                
                # prints success message to console
                logger.info('\nTrade entered successfully!')
                logger.info('Result Code: {}\n'.format(result['stringCode']))
            
            except Exception as error:
                logger.info(f"\nTrade failed with error: {error}\n")
                update.effective_message.reply_text(f"There was an issue 😕\n\nError Message:\n{error}")
    
    except Exception as error:
        logger.error(f'Error: {error}')
        update.effective_message.reply_text(f"There was an issue with the connection 😕\n\nError Message:\n{error}")
    
    return

def GetTradeInformation(update: Update, trade: dict, balance: float) -> None:
    """Calculates information from given trade including stop loss and take profit in pips, position size, and potential loss/profit.

    Arguments:
        update: update from Telegram
        trade: dictionary that stores trade information
        balance: current balance of the MetaTrader account
    """

    # calculates the position size
    trade['PositionSize'] = math.floor(((balance * trade['RiskFactor']) / (trade['TP'][0] * 10)))

    # produces the position size for user
    update.effective_message.reply_text(f"Position Size: {trade['PositionSize']} units\n")

    return

# Command Handlers
def Calculation_Command(update: Update, context: CallbackContext) -> int:
    """Calculates trade information from given signal including position size, stop loss and take profit in pips.

    Arguments:
        update: update from Telegram
        context: context from Telegram

    Returns:
        DECISION: next state in conversation
    """

    # gets signal from user
    signal = update.message.text

    # parses trade signal
    trade = ParseSignal(signal)

    # checks if signal was valid
    if(bool(trade) == False):
        update.effective_message.reply_text("Invalid Signal Format! Please enter a valid signal.")
        return ConversationHandler.END
    
    # calculates stop loss and take profit in pips
    trade['TP'] = [50.0]
    trade['StopLoss'] = None

    # produces a table with trade information
    GetTradeInformation(update, trade, context.user_data['balance'])

    # prompts user to enter trade
    update.effective_message.reply_text("Do you want to enter the trade? (yes/no)")

    return DECISION

def CalculateTrade(update: Update, context: CallbackContext) -> int:
    """Calculates information from given trade including stop loss and take profit in pips, position size, and potential loss/profit.

    Arguments:
        update: update from Telegram
        context: context from Telegram

    Returns:
        DECISION: next state in conversation
    """

    # gets signal from user
    signal = update.message.text

    # parses trade signal
    trade = ParseSignal(signal)

    # checks if signal was valid
    if(bool(trade) == False):
        update.effective_message.reply_text("Invalid Signal Format! Please enter a valid signal.")
        return ConversationHandler.END
    
    # calculates stop loss and take profit in pips
    trade['TP'] = [50.0]
    trade['StopLoss'] = None

    # produces a table with trade information
    GetTradeInformation(update, trade, context.user_data['balance'])

    # prompts user to enter trade
    update.effective_message.reply_text("Do you want to enter the trade? (yes/no)")

    return DECISION

def PlaceTrade(update: Update, context: CallbackContext) -> int:
    """Places trade on MetaTrader account.

    Arguments:
        update: update from Telegram
        context: context from Telegram

    Returns:
        ConversationHandler.END: ends conversation
    """

    # gets signal from user
    signal = update.message.text

    # parses trade signal
    trade = ParseSignal(signal)

    # checks if signal was valid
    if(bool(trade) == False):
        update.effective_message.reply_text("Invalid Signal Format! Please enter a valid signal.")
        return ConversationHandler.END

    # enters trade on to MetaTrader account
    asyncio.run(ConnectMetaTrader(update, trade, True))

    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels conversation.

    Arguments:
        update: update from Telegram
        context: context from Telegram

    Returns:
        ConversationHandler.END: ends conversation
    """

    # sends cancellation message
    update.effective_message.reply_text('Conversation canceled.')
    
    return ConversationHandler.END

def main() -> None:
    """Starts the bot."""

    # creates updater with API key from token
    updater = Updater(TOKEN)

    # adds a conversation handler to the bot
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("calculate", Calculation_Command)],
        states={
            CALCULATE: [MessageHandler(Filters.text & ~Filters.command, CalculateTrade)],
            DECISION: [CommandHandler("yes", PlaceTrade), CommandHandler("no", cancel)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    updater.dispatcher.add_handler(conv_handler)

    # starts the Bot
    updater.start_webhook(listen="0.0.0.0", port=int(PORT), url_path=TOKEN)
    updater.bot.setWebhook(APP_URL + TOKEN)

    # runs the bot until the user sends a signal to stop
    updater.idle()

if __name__ == '__main__':
    main()
