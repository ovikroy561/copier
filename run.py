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
from telegram import ParseMode, Update
from telegram.ext import MessageHandler, Filters, Updater

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
    if('Buy Limit'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Buy Limit'

    elif('Sell Limit'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Sell Limit'

    elif('Buy Stop'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Buy Stop'

    elif('Sell Stop'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Sell Stop'

    elif('Buy'.lower() in signal[0].lower()):
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
        trade['Entry'] = (signal[1].split())[-1]
    
    else:
        trade['Entry'] = float((signal[1].split())[-1])
    
    trade['StopLoss'] = float((signal[2].split())[-1])
    trade['TP'] = [float((signal[3].split())[-1])]

    # checks if there's a fourth line and parses it for TP2
    if(len(signal) > 4):
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
        GetTradeInformation(update, trade, account_information['balance'])
            
        # checks if the user has indicated to enter trade
        if(enterTrade == True):

            # enters trade on to MetaTrader account
            update.effective_message.reply_text("Entering trade on MetaTrader Account ... 👨🏾‍💻")

            try:
                # executes buy market execution order
                if(trade['OrderType'] == 'Buy'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_market_buy_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['StopLoss'], takeProfit)

                # executes buy limit order
                elif(trade['OrderType'] == 'Buy Limit'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_limit_buy_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['Entry'], trade['StopLoss'], takeProfit)

                # executes buy stop order
                elif(trade['OrderType'] == 'Buy Stop'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_stop_buy_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['Entry'], trade['StopLoss'], takeProfit)

                # executes sell market execution order
                elif(trade['OrderType'] == 'Sell'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_market_sell_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['StopLoss'], takeProfit)

                # executes sell limit order
                elif(trade['OrderType'] == 'Sell Limit'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_limit_sell_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['Entry'], trade['StopLoss'], takeProfit)

                # executes sell stop order
                elif(trade['OrderType'] == 'Sell Stop'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_stop_sell_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['Entry'], trade['StopLoss'], takeProfit)
                
                # updates the table to reflect that trade was successfully entered
                GetTradeInformation(update, trade, account_information['balance'])
                
                # sends message indicating that trade was successfully entered
                update.effective_message.reply_text("Trade Successfully Entered! 🎉")

            # sends error message if trade entry was unsuccessful
            except Exception as err:
                update.effective_message.reply_text(f"Error entering trade: {str(err)}")
            
            finally:
                # closes the connection to MetaTrader
                await connection.close()
        
        # closes the connection to MetaTrader
        else:
            await connection.close()

    # sends error message if MetaAPI connection was unsuccessful
    except Exception as err:
        update.effective_message.reply_text(f"Error connecting to MetaTrader: {str(err)}")

async def HandleTradeSignal(update: Update, context: None):
    """Handles incoming trade signals from Telegram.

    Arguments:
        update: update from Telegram
        context: unused parameter

    Returns:
        A coroutine that checks for valid signals and connects to MetaAPI/MetaTrader to place trades
    """

    # splits signal into list of strings
    trade_signal = update.message.text.splitlines()

    # checks if the signal is valid
    if(len(trade_signal) >= 4 and any(word in trade_signal[0].lower() for word in ['buy', 'sell']) and any(symbol.upper() in trade_signal[0].upper() for symbol in SYMBOLS)):
        
        # sends message indicating that the trade signal is being processed
        update.message.reply_text("Processing Trade Signal ... ⚙️")

        # parses signal and produces a trade dictionary
        trade = ParseSignal(update.message.text)

        # checks if the dictionary is not empty (i.e., signal was valid)
        if(trade != {}):
            
            # determines the position size of the trade
            trade['PositionSize'] = math.floor((trade['RiskFactor'] * trade['StopLoss']) / (trade['Entry'] - trade['StopLoss']))
            
            # connects to MetaAPI/MetaTrader to place trade
            await ConnectMetaTrader(update, trade, True)
    
    # sends message indicating that the trade signal was not valid
    else:
        update.message.reply_text("Invalid Trade Signal! Please check the format and try again. 🚫")


def GetTradeInformation(update: Update, trade: dict, account_balance: float):
    """Produces a table containing trade information to be sent to the Telegram chat.

    Arguments:
        update: update from Telegram
        trade: dictionary that stores trade information
        account_balance: balance of MetaTrader account

    Returns:
        None
    """

    # calculates the margin required for the trade
    margin_required = (trade['PositionSize'] * trade['Entry']) / trade['RiskFactor']

    # creates a table to display trade information
    table = f"""
    **Trade Information:**
    {'=' * 30}
    **Order Type:** {trade['OrderType']}
    **Symbol:** {trade['Symbol']}
    **Entry Price:** {trade['Entry']}
    **Stop Loss:** {trade['StopLoss']}
    **Take Profit:** {trade['TP'][0]}
    **Position Size:** {trade['PositionSize']}
    **Risk Factor:** {trade['RiskFactor'] * 100}%
    **Margin Required:** {margin_required}
    **Account Balance:** {account_balance}
    {'=' * 30}
    """

    # sends the table to the Telegram chat
    update.effective_message.reply_text(table, parse_mode=ParseMode.MARKDOWN)


async def error(update: Update, context: None):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

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

if __name__ == '__main__':
    asyncio.run(main())
