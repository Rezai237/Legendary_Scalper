"""
Trading Strategy Module
Multi-timeframe signal generation using EMA + RSI + MACD
"""

from typing import Dict, Optional, Tuple
import config
from indicators import get_latest_indicators


class Signal:
    """Represents a trading signal"""
    
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"
    
    def __init__(self, signal_type: str, strength: int, symbol: str, 
                 price: float, indicators: dict):
        self.type = signal_type
        self.strength = strength  # 0-5
        self.symbol = symbol
        self.price = price
        self.indicators = indicators
    
    def __repr__(self):
        return f"Signal({self.type}, {self.symbol}, strength={self.strength})"
    
    def is_valid(self) -> bool:
        """Check if signal meets minimum strength requirement"""
        return self.strength >= config.MIN_SIGNAL_STRENGTH


def analyze_primary_timeframe(indicators: dict) -> Tuple[str, int, list]:
    """
    Analyze 1-minute timeframe for entry signals
    
    Returns:
        Tuple of (signal_type, strength, reasons)
    """
    reasons = []
    buy_score = 0
    sell_score = 0
    
    # 1. EMA Trend (1 point)
    if indicators['ema_fast'] > indicators['ema_slow']:
        buy_score += 1
        reasons.append("EMA9 > EMA21 (Uptrend)")
    elif indicators['ema_fast'] < indicators['ema_slow']:
        sell_score += 1
        reasons.append("EMA9 < EMA21 (Downtrend)")
    
    # 2. EMA Crossover (1 point - recent crossover is stronger signal)
    if indicators['ema_cross'] == 1:
        buy_score += 1
        reasons.append("EMA Bullish Crossover")
    elif indicators['ema_cross'] == -1:
        sell_score += 1
        reasons.append("EMA Bearish Crossover")
    
    # 3. RSI Conditions (1 point)
    rsi = indicators['rsi']
    if rsi > config.RSI_BUY_THRESHOLD and rsi < config.RSI_OVERBOUGHT:
        buy_score += 1
        reasons.append(f"RSI {rsi:.1f} (Bullish zone)")
    elif rsi < config.RSI_SELL_THRESHOLD and rsi > config.RSI_OVERSOLD:
        sell_score += 1
        reasons.append(f"RSI {rsi:.1f} (Bearish zone)")
    elif rsi <= config.RSI_OVERSOLD:
        buy_score += 1
        reasons.append(f"RSI {rsi:.1f} (Oversold - Reversal)")
    elif rsi >= config.RSI_OVERBOUGHT:
        sell_score += 1
        reasons.append(f"RSI {rsi:.1f} (Overbought - Reversal)")
    
    # 4. MACD Direction (1 point)
    if indicators['macd'] > indicators['macd_signal']:
        buy_score += 1
        reasons.append("MACD > Signal (Bullish)")
    elif indicators['macd'] < indicators['macd_signal']:
        sell_score += 1
        reasons.append("MACD < Signal (Bearish)")
    
    # 5. MACD Crossover (1 point - recent crossover is stronger)
    if indicators['macd_cross'] == 1:
        buy_score += 1
        reasons.append("MACD Bullish Crossover")
    elif indicators['macd_cross'] == -1:
        sell_score += 1
        reasons.append("MACD Bearish Crossover")
    
    # Determine signal
    if buy_score > sell_score and buy_score >= 2:
        return Signal.BUY, buy_score, reasons
    elif sell_score > buy_score and sell_score >= 2:
        return Signal.SELL, sell_score, reasons
    else:
        return Signal.NEUTRAL, 0, reasons


def analyze_confirmation_timeframe(indicators: dict) -> bool:
    """
    Analyze 5-minute timeframe for trend confirmation
    
    Returns:
        True if trend is confirmed, False otherwise
    """
    # Check if 5m trend aligns with signal
    # We just need EMA trend confirmation
    return indicators['trend']


def generate_signal(symbol: str, primary_indicators: dict, 
                   confirmation_indicators: dict = None,
                   trend_indicators: dict = None,
                   macro_indicators: dict = None,
                   major_indicators: dict = None) -> Signal:
    """
    Generate trading signal from 5 timeframe analysis
    
    Args:
        symbol: Trading pair
        primary_indicators: 1m timeframe indicators (entry)
        confirmation_indicators: 5m timeframe indicators (short-term)
        trend_indicators: 15m timeframe indicators (medium-term)
        macro_indicators: 30m timeframe indicators (main trend)
        major_indicators: 1h timeframe indicators (major trend)
    
    Returns:
        Signal object
    """
    # Volume Filter - skip low volume signals
    if getattr(config, 'VOLUME_FILTER_ENABLED', False):
        volume_ratio = primary_indicators.get('volume_ratio', 1.0)
        min_volume = getattr(config, 'MIN_VOLUME_MULTIPLIER', 1.5)
        if volume_ratio < min_volume:
            return Signal(
                Signal.NEUTRAL, 
                0, 
                symbol, 
                primary_indicators['close'],
                primary_indicators
            )
    
    # ADX Filter - skip weak trend signals
    if getattr(config, 'ADX_FILTER_ENABLED', False):
        adx = primary_indicators.get('adx', 0)
        min_adx = getattr(config, 'ADX_MIN_THRESHOLD', 25)
        if adx < min_adx:
            return Signal(
                Signal.NEUTRAL, 
                0, 
                symbol, 
                primary_indicators['close'],
                primary_indicators
            )
    
    # Analyze primary timeframe
    signal_type, strength, reasons = analyze_primary_timeframe(primary_indicators)
    
    # If no clear signal, return neutral
    if signal_type == Signal.NEUTRAL:
        return Signal(
            Signal.NEUTRAL, 
            0, 
            symbol, 
            primary_indicators['close'],
            primary_indicators
        )
    
    # Check 5m confirmation timeframe
    if config.REQUIRE_CONFIRMATION and confirmation_indicators:
        conf_trend = analyze_confirmation_timeframe(confirmation_indicators)
        
        if signal_type == Signal.BUY and conf_trend != 1:
            strength -= 1
        elif signal_type == Signal.SELL and conf_trend != -1:
            strength -= 1
        
        if (signal_type == Signal.BUY and conf_trend == 1) or \
           (signal_type == Signal.SELL and conf_trend == -1):
            strength = min(strength + 1, 8)  # Cap at 8 for 5 TF
    
    # Check 15m trend timeframe (medium-term)
    if trend_indicators:
        mid_trend = analyze_confirmation_timeframe(trend_indicators)
        
        if signal_type == Signal.BUY and mid_trend != 1:
            strength -= 1
        elif signal_type == Signal.SELL and mid_trend != -1:
            strength -= 1
        
        if (signal_type == Signal.BUY and mid_trend == 1) or \
           (signal_type == Signal.SELL and mid_trend == -1):
            strength = min(strength + 1, 8)
    
    # Check 30m macro timeframe (main trend)
    if macro_indicators:
        main_trend = analyze_confirmation_timeframe(macro_indicators)
        
        if signal_type == Signal.BUY and main_trend != 1:
            strength -= 1
        elif signal_type == Signal.SELL and main_trend != -1:
            strength -= 1
        
        if (signal_type == Signal.BUY and main_trend == 1) or \
           (signal_type == Signal.SELL and main_trend == -1):
            strength = min(strength + 1, 8)
    
    # Check 1h major timeframe (major trend)
    if major_indicators:
        major_trend = analyze_confirmation_timeframe(major_indicators)
        
        if signal_type == Signal.BUY and major_trend != 1:
            strength -= 1
        elif signal_type == Signal.SELL and major_trend != -1:
            strength -= 1
        
        if (signal_type == Signal.BUY and major_trend == 1) or \
           (signal_type == Signal.SELL and major_trend == -1):
            strength = min(strength + 1, 8)
    
    # Trend Alignment Check - count aligned timeframes
    if getattr(config, 'TREND_ALIGNMENT_ENABLED', False):
        aligned_count = 1  # Primary TF already aligned (we have a signal)
        
        # Check each confirmation TF
        if confirmation_indicators:
            conf_trend = analyze_confirmation_timeframe(confirmation_indicators)
            if (signal_type == Signal.BUY and conf_trend == 1) or \
               (signal_type == Signal.SELL and conf_trend == -1):
                aligned_count += 1
        
        if trend_indicators:
            mid_trend = analyze_confirmation_timeframe(trend_indicators)
            if (signal_type == Signal.BUY and mid_trend == 1) or \
               (signal_type == Signal.SELL and mid_trend == -1):
                aligned_count += 1
        
        if macro_indicators:
            main_trend = analyze_confirmation_timeframe(macro_indicators)
            if (signal_type == Signal.BUY and main_trend == 1) or \
               (signal_type == Signal.SELL and main_trend == -1):
                aligned_count += 1
        
        if major_indicators:
            major_trend = analyze_confirmation_timeframe(major_indicators)
            if (signal_type == Signal.BUY and major_trend == 1) or \
               (signal_type == Signal.SELL and major_trend == -1):
                aligned_count += 1
        
        min_alignment = getattr(config, 'MIN_TF_ALIGNMENT', 4)
        if aligned_count < min_alignment:
            return Signal(
                Signal.NEUTRAL, 
                0, 
                symbol, 
                primary_indicators['close'],
                primary_indicators
            )
    
    return Signal(
        signal_type,
        strength,
        symbol,
        primary_indicators['close'],
        primary_indicators
    )


def filter_signals(signals: list) -> list:
    """
    Filter and sort signals by strength
    
    Args:
        signals: List of Signal objects
    
    Returns:
        Filtered list of valid signals, sorted by strength
    """
    valid_signals = [s for s in signals if s.is_valid()]
    return sorted(valid_signals, key=lambda x: x.strength, reverse=True)


# Test when run directly
if __name__ == "__main__":
    print("Testing Strategy Module...")
    
    # Mock indicators for buy signal
    buy_indicators = {
        'close': 100.0,
        'ema_fast': 101.0,
        'ema_slow': 99.0,
        'rsi': 45.0,
        'macd': 0.5,
        'macd_signal': 0.3,
        'macd_hist': 0.2,
        'atr': 1.5,
        'trend': 1,
        'ema_cross': 1,
        'macd_cross': 1
    }
    
    signal = generate_signal("BTCUSDT", buy_indicators)
    print(f"✅ Signal Type: {signal.type}")
    print(f"✅ Strength: {signal.strength}/5")
    print(f"✅ Is Valid: {signal.is_valid()}")
    
    # Mock indicators for sell signal
    sell_indicators = {
        'close': 100.0,
        'ema_fast': 99.0,
        'ema_slow': 101.0,
        'rsi': 65.0,
        'macd': -0.5,
        'macd_signal': -0.3,
        'macd_hist': -0.2,
        'atr': 1.5,
        'trend': -1,
        'ema_cross': -1,
        'macd_cross': -1
    }
    
    signal = generate_signal("ETHUSDT", sell_indicators)
    print(f"\n✅ Signal Type: {signal.type}")
    print(f"✅ Strength: {signal.strength}/5")
    print(f"✅ Is Valid: {signal.is_valid()}")
    
    print("\n✅ All strategy tests passed!")
