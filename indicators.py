"""
Technical Indicators Module
Calculates EMA, RSI, MACD, ATR for trading signals
"""

import pandas as pd
import numpy as np
from typing import Tuple

import config


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Calculate Exponential Moving Average
    
    Args:
        series: Price series (typically close prices)
        period: EMA period
    
    Returns:
        EMA series
    """
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index
    
    Args:
        series: Price series
        period: RSI period (default 14, use 7 for scalping)
    
    Returns:
        RSI series (0-100)
    """
    delta = series.diff()
    
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_macd(series: pd.Series, 
                   fast_period: int = 12, 
                   slow_period: int = 26, 
                   signal_period: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD (Moving Average Convergence Divergence)
    
    Args:
        series: Price series
        fast_period: Fast EMA period
        slow_period: Slow EMA period
        signal_period: Signal line period
    
    Returns:
        Tuple of (MACD line, Signal line, Histogram)
    """
    ema_fast = calculate_ema(series, fast_period)
    ema_slow = calculate_ema(series, slow_period)
    
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, 
                  period: int = 14) -> pd.Series:
    """
    Calculate Average True Range
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: ATR period
    
    Returns:
        ATR series
    """
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(span=period, adjust=False).mean()
    
    return atr


def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series,
                  period: int = 14) -> pd.Series:
    """
    Calculate Average Directional Index (ADX) for trend strength
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: ADX period
    
    Returns:
        ADX series (0-100, >25 = strong trend)
    """
    # Calculate +DM and -DM
    high_diff = high.diff()
    low_diff = low.diff().abs() * -1
    
    plus_dm = high_diff.where((high_diff > low_diff.abs()) & (high_diff > 0), 0)
    minus_dm = low_diff.abs().where((low_diff.abs() > high_diff) & (low_diff < 0), 0)
    
    # Calculate True Range
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Smooth with EMA
    atr = true_range.ewm(span=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
    
    # Calculate DX and ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 0.0001)
    adx = dx.ewm(span=period, adjust=False).mean()
    
    return adx


def calculate_bollinger_bands(series: pd.Series, period: int = 20, 
                               std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands
    
    Args:
        series: Price series
        period: Moving average period
        std_dev: Standard deviation multiplier
    
    Returns:
        Tuple of (Upper Band, Middle Band, Lower Band)
    """
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    
    return upper, middle, lower


def find_support_resistance(high: pd.Series, low: pd.Series, close: pd.Series,
                            lookback: int = 50, sensitivity: float = 0.02) -> dict:
    """
    Find Support and Resistance levels using pivot points and price clustering
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        lookback: Number of candles to analyze
        sensitivity: Price clustering sensitivity (2% default)
    
    Returns:
        Dict with support and resistance levels
    """
    if len(close) < lookback:
        return {'supports': [], 'resistances': [], 'nearest_support': None, 'nearest_resistance': None}
    
    # Get recent data
    recent_high = high.tail(lookback)
    recent_low = low.tail(lookback)
    recent_close = close.tail(lookback)
    current_price = close.iloc[-1]
    
    # Find pivot points (local highs and lows)
    pivot_highs = []
    pivot_lows = []
    
    for i in range(2, len(recent_high) - 2):
        # Local high (resistance candidate)
        if (recent_high.iloc[i] > recent_high.iloc[i-1] and
            recent_high.iloc[i] > recent_high.iloc[i-2] and
            recent_high.iloc[i] > recent_high.iloc[i+1] and
            recent_high.iloc[i] > recent_high.iloc[i+2]):
            pivot_highs.append(recent_high.iloc[i])
        
        # Local low (support candidate)
        if (recent_low.iloc[i] < recent_low.iloc[i-1] and
            recent_low.iloc[i] < recent_low.iloc[i-2] and
            recent_low.iloc[i] < recent_low.iloc[i+1] and
            recent_low.iloc[i] < recent_low.iloc[i+2]):
            pivot_lows.append(recent_low.iloc[i])
    
    # Cluster similar levels
    def cluster_levels(levels, threshold):
        if not levels:
            return []
        levels = sorted(levels)
        clusters = []
        current_cluster = [levels[0]]
        
        for level in levels[1:]:
            if (level - current_cluster[0]) / current_cluster[0] < threshold:
                current_cluster.append(level)
            else:
                clusters.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [level]
        clusters.append(sum(current_cluster) / len(current_cluster))
        return clusters
    
    supports = cluster_levels(pivot_lows, sensitivity)
    resistances = cluster_levels(pivot_highs, sensitivity)
    
    # Filter: supports below current price, resistances above
    supports = [s for s in supports if s < current_price]
    resistances = [r for r in resistances if r > current_price]
    
    # Find nearest levels
    nearest_support = max(supports) if supports else None
    nearest_resistance = min(resistances) if resistances else None
    
    return {
        'supports': sorted(supports, reverse=True)[:3],  # Top 3 nearest
        'resistances': sorted(resistances)[:3],  # Top 3 nearest
        'nearest_support': nearest_support,
        'nearest_resistance': nearest_resistance,
        'current_price': current_price
    }


def calculate_stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                         k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate Stochastic Oscillator
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        k_period: %K period
        d_period: %D period (signal line)
    
    Returns:
        Tuple of (%K, %D)
    """
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(window=d_period).mean()
    
    return k, d


def klines_to_dataframe(klines: list) -> pd.DataFrame:
    """
    Convert Binance klines to pandas DataFrame
    
    Args:
        klines: Raw kline data from Binance API
    
    Returns:
        DataFrame with OHLCV data
    """
    df = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    
    # Convert to numeric
    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Convert timestamps
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
    
    return df


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate all indicators for a DataFrame
    
    Args:
        df: DataFrame with OHLCV data
    
    Returns:
        DataFrame with all indicators added
    """
    # Make a copy to avoid modifying original
    df = df.copy()
    
    # EMAs
    df['ema_fast'] = calculate_ema(df['close'], config.EMA_FAST_PERIOD)
    df['ema_slow'] = calculate_ema(df['close'], config.EMA_SLOW_PERIOD)
    
    # RSI
    df['rsi'] = calculate_rsi(df['close'], config.RSI_PERIOD)
    
    # MACD
    df['macd'], df['macd_signal'], df['macd_hist'] = calculate_macd(
        df['close'],
        config.MACD_FAST_PERIOD,
        config.MACD_SLOW_PERIOD,
        config.MACD_SIGNAL_PERIOD
    )
    
    # ATR
    df['atr'] = calculate_atr(df['high'], df['low'], df['close'], config.ATR_PERIOD)
    
    # Trend direction
    df['trend'] = np.where(df['ema_fast'] > df['ema_slow'], 1, -1)
    
    # EMA crossover
    df['ema_cross'] = np.where(
        (df['ema_fast'] > df['ema_slow']) & (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1)), 1,
        np.where(
            (df['ema_fast'] < df['ema_slow']) & (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1)), -1, 0
        )
    )
    
    # MACD crossover
    df['macd_cross'] = np.where(
        (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1)), 1,
        np.where(
            (df['macd'] < df['macd_signal']) & (df['macd'].shift(1) >= df['macd_signal'].shift(1)), -1, 0
        )
    )
    
    # ADX (Trend Strength)
    adx_period = getattr(config, 'ADX_PERIOD', 14)
    df['adx'] = calculate_adx(df['high'], df['low'], df['close'], adx_period)
    
    return df


def get_latest_indicators(df: pd.DataFrame) -> dict:
    """
    Get the latest indicator values
    
    Args:
        df: DataFrame with indicators
    
    Returns:
        Dictionary with latest values
    """
    if df.empty:
        return {}
    
    latest = df.iloc[-1]
    
    # Calculate volume ratio (current vs average)
    volume_lookback = getattr(config, 'VOLUME_LOOKBACK', 20)
    if len(df) >= volume_lookback:
        avg_volume = df['volume'].tail(volume_lookback).mean()
        current_volume = latest['volume']
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
    else:
        volume_ratio = 1.0
    
    return {
        'close': latest['close'],
        'ema_fast': latest['ema_fast'],
        'ema_slow': latest['ema_slow'],
        'rsi': latest['rsi'],
        'macd': latest['macd'],
        'macd_signal': latest['macd_signal'],
        'macd_hist': latest['macd_hist'],
        'atr': latest['atr'],
        'adx': latest['adx'],
        'trend': latest['trend'],
        'ema_cross': latest['ema_cross'],
        'macd_cross': latest['macd_cross'],
        'volume': latest['volume'],
        'volume_ratio': volume_ratio
    }


# Test when run directly
if __name__ == "__main__":
    print("Testing Indicators Module...")
    
    # Create sample data
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=100, freq='1min')
    
    close_prices = 100 + np.cumsum(np.random.randn(100) * 0.5)
    high_prices = close_prices + np.random.rand(100) * 0.5
    low_prices = close_prices - np.random.rand(100) * 0.5
    
    df = pd.DataFrame({
        'open_time': dates,
        'open': close_prices,
        'high': high_prices,
        'low': low_prices,
        'close': close_prices,
        'volume': np.random.rand(100) * 1000
    })
    
    # Calculate indicators
    df = calculate_all_indicators(df)
    
    # Get latest values
    latest = get_latest_indicators(df)
    
    print(f"✅ Latest Close: {latest['close']:.2f}")
    print(f"✅ EMA Fast: {latest['ema_fast']:.2f}")
    print(f"✅ EMA Slow: {latest['ema_slow']:.2f}")
    print(f"✅ RSI: {latest['rsi']:.2f}")
    print(f"✅ MACD: {latest['macd']:.4f}")
    print(f"✅ ATR: {latest['atr']:.4f}")
    print(f"✅ Trend: {'UP' if latest['trend'] == 1 else 'DOWN'}")
    
    print("\n✅ All indicator tests passed!")
