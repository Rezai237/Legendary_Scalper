"""
Configuration Module for Binance Scalping Bot
Contains all settings, API keys, and trading parameters
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =============================================================================
# API CONFIGURATION (Binance Testnet)
# =============================================================================
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# Use Testnet for safety
USE_TESTNET = True

# Base URLs
TESTNET_BASE_URL = "https://testnet.binancefuture.com"
PRODUCTION_BASE_URL = "https://fapi.binance.com"

def get_base_url():
    return TESTNET_BASE_URL if USE_TESTNET else PRODUCTION_BASE_URL

# =============================================================================
# GROK AI CONFIGURATION
# =============================================================================
GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_MODEL = "grok-4-1-fast-reasoning"
GROK_BASE_URL = "https://api.x.ai/v1"

# Grok Analysis Settings
GROK_ENABLED = True                   # Enable Grok AI analysis
GROK_MARKET_REGIME_INTERVAL = 30      # Market regime check every 30 minutes
GROK_NEWS_ANALYSIS_HOUR = 8           # Daily news analysis at 8:00 UTC

# Vision Analysis Settings
VISION_ENABLED = True                 # Enable chart vision analysis
VISION_ANALYSIS_INTERVAL = 3          # Analyze charts every 3 minutes
VISION_MIN_CONFIDENCE = 0.6           # Minimum confidence to use vision SL/TP

# =============================================================================
# SCANNING CONFIGURATION
# =============================================================================
SCAN_INTERVAL_SECONDS = 10      # Scan every 10 seconds
TOP_PAIRS_COUNT = 30            # Number of top pairs to scan
QUOTE_ASSET = "USDT"            # Only USDT pairs

# Volatility-Based Pair Selection
VOLATILITY_REFRESH_MINUTES = 5  # Refresh top pairs every 5 minutes
MIN_VOLATILITY_PERCENT = 1.0    # Minimum 24h price change to consider
USE_VOLATILITY_RANKING = True   # Use volatility ranking (scan all pairs every 5 min)
MIN_24H_VOLUME_USDT = 3000000   # Minimum $3M daily volume (liquidity filter)

# Blacklist (dangerous/risky coins to avoid)
BLACKLIST = [
    "LUNAUSDT",     # High risk - depegged
    "USTCUSDT",     # Depegged stablecoin
    "LUNCUSDT",     # High volatility risk
    "1000LUNCUSDT", # Same as LUNC
    "测试测试USDT",  # Test symbol - causes PERCENT_PRICE errors
]

# =============================================================================
# TIMEFRAME CONFIGURATION (5 Timeframes)
# =============================================================================
PRIMARY_TIMEFRAME = "1m"        # Entry signals
CONFIRMATION_TIMEFRAME = "5m"   # Short-term trend confirmation
TREND_TIMEFRAME = "15m"         # Medium-term trend
MACRO_TIMEFRAME = "30m"         # Main trend
MAJOR_TIMEFRAME = "1h"          # Major trend direction
KLINES_LIMIT = 100              # Number of candles to fetch

# =============================================================================
# INDICATOR SETTINGS
# =============================================================================
# EMA Settings
EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21

# RSI Settings (shorter for scalping)
RSI_PERIOD = 7
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_BUY_THRESHOLD = 40          # RSI should be above this for buy
RSI_SELL_THRESHOLD = 60         # RSI should be below this for sell

# MACD Settings
MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9

# ATR for Stop Loss
ATR_PERIOD = 14

# ADX Settings (Trend Strength Filter)
ADX_PERIOD = 14
ADX_FILTER_ENABLED = True         # Only trade when trend is strong
ADX_MIN_THRESHOLD = 25            # Minimum ADX for strong trend

# =============================================================================
# DAILY LOSS LIMIT
# =============================================================================
DAILY_LOSS_LIMIT_ENABLED = True   # Enable daily loss limit
MAX_DAILY_LOSS_PERCENT = 5.0      # Stop trading after 5% daily loss
DAILY_RESET_HOUR = 0              # Reset at midnight UTC

# =============================================================================
# TRADING PARAMETERS
# =============================================================================
LEVERAGE = 10                   # Futures leverage (10x for Martingale)
MARGIN_TYPE = "CROSSED"         # CROSSED or ISOLATED

# Capital Management
TOTAL_CAPITAL_USDT = 400       # Fixed total capital to use (4000 USDT)
USE_FIXED_CAPITAL = True        # Use fixed capital instead of account balance

# Position Sizing (Initial Margin based)
RISK_PER_TRADE_PERCENT = 2.0    # % of capital to risk per trade
MAX_POSITION_SIZE_PERCENT = 15  # Maximum position size as % of capital
INITIAL_MARGIN_PER_TRADE = 40   # Initial margin per trade in USDT (Position Value = 40 * 5 = 200 USDT)

# =============================================================================
# RISK MANAGEMENT
# =============================================================================
MAX_OPEN_POSITIONS = 15         # Maximum simultaneous positions
STOP_LOSS_ATR_MULTIPLIER = 2.0  # Stop loss = ATR * multiplier (wider SL)
TAKE_PROFIT_RR_RATIO = 2.0      # Take profit = Risk * ratio

# Minimum profit target in percentage
MIN_PROFIT_TARGET_PERCENT = 0.3
MAX_LOSS_PERCENT = 0.5

# =============================================================================
# TRAILING STOP SETTINGS
# =============================================================================
TRAILING_STOP_ENABLED = True          # Enable trailing stop loss
TRAILING_STOP_ACTIVATION = 1.0        # Activate after 1% profit
TRAILING_STOP_CALLBACK = 0.5          # Trail 0.5% behind price

# Break-even Stop (move SL to entry after profit)
BREAKEVEN_ENABLED = True              # Enable break-even stop
BREAKEVEN_ACTIVATION = 0.5            # Move SL to entry after 0.5% profit

# =============================================================================
# VOLUME FILTER SETTINGS
# =============================================================================
VOLUME_FILTER_ENABLED = True          # Enable volume filter
MIN_VOLUME_MULTIPLIER = 1.5           # Volume must be 1.5x average
VOLUME_LOOKBACK = 20                  # Look at last 20 candles for average

# =============================================================================
# TREND ALIGNMENT SETTINGS
# =============================================================================
TREND_ALIGNMENT_ENABLED = True        # Require multiple TF alignments
MIN_TF_ALIGNMENT = 4                  # At least 4 out of 5 TF must agree

# =============================================================================
# PARTIAL TAKE PROFIT
# =============================================================================
PARTIAL_TP_ENABLED = True             # Enable partial take profit
PARTIAL_TP_PERCENT = 50               # Close 50% of position at first TP
PARTIAL_TP_ACTIVATION = 1.0           # Activate after 1% profit

# =============================================================================
# SIGNAL SETTINGS
# =============================================================================
MIN_SIGNAL_STRENGTH = 6         # Minimum score to enter trade (increased for quality)
REQUIRE_CONFIRMATION = True     # Require 5m timeframe confirmation

# =============================================================================
# VISION QUALITY SETTINGS (High Quality Trades)
# =============================================================================
VISION_ENABLED = False          # DISABLED - for faster scanning
VISION_REQUIRE_CONFIRM = False  # Don't require Vision signal match (option C)
VISION_REQUIRE_SL_TP = False    # Use Vision SL/TP if available, else fallback to ATR
VISION_MIN_CONFIDENCE = 65      # Minimum Vision confidence % (0-100)

# =============================================================================
# MARTINGALE SCALPER SETTINGS (Counter-Trend Strategy)
# =============================================================================
MARTINGALE_ENABLED = True       # Enable Martingale mode
MARTINGALE_MIN_PUMP = 30        # Minimum pump % to consider coin (30%+)
MARTINGALE_MAX_POSITIONS = 5    # Max concurrent Martingale positions
MARTINGALE_EMERGENCY_STOP = 35  # Emergency close at -35% drawdown (allows all 9 steps)
MARTINGALE_HARD_STOP_USD = 100  # Emergency close at -$100 loss (dollar based)
MARTINGALE_HALF_CLOSE_PERCENT = 2  # Close half when within 2% of average
MARTINGALE_TP_PERCENT = 1.5     # Take profit at 1.5% profit

# Martingale Steps: [margin per step in USDT] - 9 Steps (for $400 account)
MARTINGALE_STEPS = [
    4, 4, 6, 6, 8,       # Steps 1-5 (Early probing)
    11, 16, 21, 26       # Steps 6-9 (Building position)
]

# Distance % from average before next step allowed
MARTINGALE_STEP_DISTANCES = [
    0, 3, 5, 8, 12,     # Steps 1-5
    16, 20, 25, 30      # Steps 6-9
]

# Minimum wait time (minutes) between steps
MARTINGALE_STEP_WAIT_TIMES = [
    0, 2, 2, 3, 3,      # Steps 1-5 (Fast)
    5, 5, 10, 10        # Steps 6-9 (Medium)
]

# Dynamic Blacklist Settings (prevent repeated losses on same token)
DYNAMIC_BLACKLIST_ENABLED = True          # Enable automatic token blacklisting
DYNAMIC_BLACKLIST_STOP_LOSSES = 2         # Number of stop losses to trigger blacklist
DYNAMIC_BLACKLIST_WINDOW_HOURS = 2        # Time window to count stop losses (hours)
DYNAMIC_BLACKLIST_DURATION_HOURS = 6      # Blacklist duration (hours)

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = "INFO"              # DEBUG, INFO, WARNING, ERROR
LOG_TO_FILE = True
LOG_FILE_PATH = "trading_log.txt"
TRADE_LOG_FILE = "trades.csv"

# =============================================================================
# DISPLAY SETTINGS
# =============================================================================
DISPLAY_REFRESH_RATE = 1        # Console update rate in seconds
SHOW_INDICATORS = True          # Show indicator values in console
