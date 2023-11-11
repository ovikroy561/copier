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

# Add the missing import statements
from telegram.ext import CallbackContext
from telegram.ext import MessageHandler
from telegram.ext import Filters

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

def GetTradeInformation(update: Update, trade: dict, balance: float) -> None:
    """Calculates information from given trade including stop loss and take profit in pips, position size, and potential loss/profit.

    Arguments:
        update: update from Telegram
        trade: dictionary that stores trade information
        balance: current balance of the MetaTrader account
    """

    # calculates the stop loss in pips
    if(trade['Symbol'] == 'XAUUSD'):
        multiplier = 0.1

    elif(trade['Symbol'] == 'XAGUSD'):
        multiplier = 0.001

    elif(str(trade['Entry']).index('.') >= 2):
        multiplier = 0.01

    else:
        multiplier = 0.0001

    # calculates the stop loss in pips
    stopLossPips = abs(round((trade['StopLoss'] - trade['Entry']) / multiplier))

    # calculates the position size using stop loss and RISK FACTOR
    trade['PositionSize'] = math.floor(((balance * trade['RiskFactor']) / stopLossPips) / 10 * 100) / 100

    # calculates the take profit(s) in pips
    takeProfitPips = []
    for takeProfit in trade['TP']:
        takeProfitPips.append(abs(round((takeProfit - trade['Entry']) / multiplier)))

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

    table.add_row([trade["OrderType"] , trade["Symbol"]])
    table.add_row(['Entry\n', trade['Entry']])

    table.add_row(['Stop Loss', '{} pips'.format(stopLossPips)])

    for count, takeProfit in enumerate(takeProfitPips):
        table.add_row([f'Take Profit {count + 1}', f'{takeProfit} pips'])

    table.add_row(['Risk Factor', trade['RiskFactor']])
    table.add_row(['Balance', balance])
    table.add_row(['Position Size', trade['PositionSize']])
    table.add_row(['Potential Loss', round((trade['PositionSize'] * stopLossPips * -1) * trade['RiskFactor'], 2)])
    table.add_row(['Potential Profit', round((trade['PositionSize'] * takeProfitPips[0]) * trade['RiskFactor'], 2)])

    return table

async def ReceiveSignal(update: Update, context: CallbackContext) -> int:
    """Receives signal from user and starts process of entering trade on MetaTrader account.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks

    Returns:
        DECISION state for the conversation handler
    """

    # gets MetaTrader account information
    MetaApi.host = "trade.metaapi.io"
    api = MetaApi(token=API_KEY)
    account = await api.metatrader_get_account(accountId=ACCOUNT_ID)

    balance = account['balance']

    # receives trade signal from user
    signal = update.message.text
    trade = ParseSignal(signal)

    # checks if an invalid signal was given and restarts the conversation
    if(trade == {}):
        update.effective_message.reply_text('Invalid Signal. Please enter a valid trading signal.')
        return CALCULATE

    # sends user trade information and calculated risk
    GetTradeInformation(update, trade, balance)

    # sends user decision message
    update.effective_message.reply_text('Do you want to enter this trade?', reply_markup=ForceReply())

    return DECISION

async def Decision(update: Update, context: CallbackContext) -> int:
    """Receives user decision and starts process of entering trade on MetaTrader account.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks

    Returns:
        CALCULATE state for the conversation handler
    """

    # gets user decision
    decision = update.message.text

    # enters trade if user says 'yes'
    if(decision.lower() == 'yes'):
        MetaApi.host = "trade.metaapi.io"
        api = MetaApi(token=API_KEY)
        
        # opens trade
        await api.metatrader_create_market_buy_order(accountId=ACCOUNT_ID, symbol=trade['Symbol'], volume=trade['PositionSize'], stopLoss=trade['StopLoss'], takeProfit=trade['TP'][0])
        
        # sends user confirmation message
        update.effective_message.reply_text('Trade successfully entered. Good luck!')

        return CALCULATE

    # restarts conversation if user says 'no'
    elif(decision.lower() == 'no'):
        update.effective_message.reply_text('Trade cancelled. Please enter a new trading signal.')

        return CALCULATE

    # asks user to confirm decision if input is not recognized
    else:
        update.effective_message.reply_text('Invalid input. Please enter "yes" or "no" to confirm if you want to enter this trade.')

        return DECISION

async def main():
    """Runs the bot."""
    # sets up the updater and dispatcher
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    # adds handlers for different commands and messages
    dp.add_handler(CommandHandler("start", welcome))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("calculate", calculate))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, receive_signal))
    dp.add_handler(ConversationHandler(
        entry_points=[MessageHandler(Filters.text & ~Filters.command, receive_signal)],
        states={
            CALCULATE: [MessageHandler(Filters.text & ~Filters.command, receive_signal)],
            DECISION: [MessageHandler(Filters.text & ~Filters.command, decision)],
        },
        fallbacks=[],
    ))

    # starts the Bot
    updater.start_polling()

    # Run the bot until you send a signal to stop
    updater.idle()

if __name__ == '__main__':
    asyncio.run(main())
