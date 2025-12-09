"""
Logger Module for Binance Scalping Bot
Provides colored console output and file logging
"""

import logging
import os
from datetime import datetime
from colorama import init, Fore, Style, Back

import config

# Initialize colorama for Windows support
init()


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""
    
    COLORS = {
        'DEBUG': Fore.CYAN,
        'INFO': Fore.GREEN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.RED + Back.WHITE,
    }
    
    def format(self, record):
        color = self.COLORS.get(record.levelname, Fore.WHITE)
        record.levelname = f"{color}{record.levelname}{Style.RESET_ALL}"
        record.msg = f"{color}{record.msg}{Style.RESET_ALL}"
        return super().format(record)


def setup_logger(name: str = "ScalpingBot") -> logging.Logger:
    """Setup and return a configured logger"""
    
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.LOG_LEVEL))
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Console handler with colors
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_format = ColoredFormatter(
        '%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler (if enabled)
    if config.LOG_TO_FILE:
        file_handler = logging.FileHandler(config.LOG_FILE_PATH, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger


def log_signal(symbol: str, signal_type: str, strength: int, price: float):
    """Log a trading signal with special formatting"""
    if signal_type == "BUY":
        color = Fore.GREEN + Style.BRIGHT
        emoji = "🟢"
    elif signal_type == "SELL":
        color = Fore.RED + Style.BRIGHT
        emoji = "🔴"
    else:
        color = Fore.YELLOW
        emoji = "⚪"
    
    print(f"{color}{emoji} SIGNAL: {signal_type} {symbol} | Strength: {strength}/5 | Price: {price:.4f}{Style.RESET_ALL}")


def log_trade(symbol: str, side: str, quantity: float, price: float, 
              stop_loss: float, take_profit: float, order_id: str):
    """Log trade execution to CSV file"""
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Create header if file doesn't exist
    if not os.path.exists(config.TRADE_LOG_FILE):
        with open(config.TRADE_LOG_FILE, 'w') as f:
            f.write("timestamp,symbol,side,quantity,price,stop_loss,take_profit,order_id\n")
    
    # Append trade
    with open(config.TRADE_LOG_FILE, 'a') as f:
        f.write(f"{timestamp},{symbol},{side},{quantity},{price},{stop_loss},{take_profit},{order_id}\n")


def print_banner():
    """Print bot startup banner"""
    banner = f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════╗
║  {Fore.YELLOW}🚀 BINANCE MULTI-TIMEFRAME SCALPING BOT 🚀{Fore.CYAN}                  ║
║                                                                ║
║  {Fore.WHITE}Strategy: EMA + RSI + MACD Triple Confirmation{Fore.CYAN}              ║
║  {Fore.WHITE}Timeframes: 1m (Entry) + 5m (Confirmation){Fore.CYAN}                  ║
║  {Fore.WHITE}Scanning: {config.TOP_PAIRS_COUNT} pairs every {config.SCAN_INTERVAL_SECONDS} seconds{Fore.CYAN}                        ║
║                                                                ║
║  {Fore.GREEN if config.USE_TESTNET else Fore.RED}Mode: {'TESTNET' if config.USE_TESTNET else 'PRODUCTION'}{Fore.CYAN}                                           ║
╚══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}
"""
    print(banner)


def print_scan_header(scan_number: int, pairs_count: int):
    """Print scan iteration header"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}📊 Scan #{scan_number} | {timestamp} | Analyzing {pairs_count} pairs{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")


def print_position_summary(positions: list):
    """Print current positions summary"""
    if not positions:
        print(f"{Fore.YELLOW}📭 No open positions{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.WHITE}📈 Open Positions ({len(positions)}/{config.MAX_OPEN_POSITIONS}):{Style.RESET_ALL}")
    for pos in positions:
        pnl_color = Fore.GREEN if pos.get('unrealizedProfit', 0) >= 0 else Fore.RED
        print(f"  {pos['symbol']}: {pos['positionAmt']} @ {pos['entryPrice']} | PnL: {pnl_color}{pos.get('unrealizedProfit', 0):.2f} USDT{Style.RESET_ALL}")


# Create default logger instance
logger = setup_logger()
