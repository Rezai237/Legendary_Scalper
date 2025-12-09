"""
Pump Detector - Find coins that pumped >30% for counter-trend trading
"""

import time
from typing import List, Dict, Optional
from logger import logger
import config


class PumpDetector:
    """Detect pumped coins for Martingale counter-trend trading"""
    
    def __init__(self, client):
        self.client = client
        self.min_pump_percent = getattr(config, 'MARTINGALE_MIN_PUMP', 30)
        self.last_scan = 0
        self.pumped_coins = []
        
    def find_pumped_coins(self) -> List[Dict]:
        """
        Find coins with significant pump in 24h
        
        Returns:
            List of dicts with symbol, pump_percent, price info
        """
        try:
            tickers = self.client.get_ticker_24h()
            
            # Get blacklist and volume settings
            blacklist = getattr(config, 'BLACKLIST', [])
            min_volume = getattr(config, 'MIN_24H_VOLUME_USDT', 500000)  # $500K default
            
            pumped = []
            filtered_low_volume = 0
            filtered_blacklist = 0
            
            for ticker in tickers:
                symbol = ticker.get('symbol', '')
                
                # Only USDT pairs
                if not symbol.endswith('USDT'):
                    continue
                    
                # Skip special pairs
                if any(x in symbol for x in ['_', 'DEFI', 'INDEX']):
                    continue
                
                # Skip blacklisted symbols
                if symbol in blacklist:
                    filtered_blacklist += 1
                    continue
                
                try:
                    price_change = float(ticker.get('priceChangePercent', 0))
                    volume_24h = float(ticker.get('quoteVolume', 0) or 0)
                    
                    # Volume filter - skip low liquidity coins
                    if volume_24h < min_volume:
                        filtered_low_volume += 1
                        continue
                    
                    if price_change >= self.min_pump_percent:
                        pumped.append({
                            'symbol': symbol,
                            'pump_percent': price_change,
                            'price': float(ticker.get('lastPrice', 0)),
                            'high_24h': float(ticker.get('highPrice', 0)),
                            'low_24h': float(ticker.get('lowPrice', 0)),
                            'volume': volume_24h
                        })
                except (ValueError, TypeError):
                    continue
            
            # Sort by pump percent (highest first)
            pumped.sort(key=lambda x: x['pump_percent'], reverse=True)
            
            self.pumped_coins = pumped
            self.last_scan = time.time()
            
            if pumped:
                logger.info(f"🔥 Found {len(pumped)} pumped coins (>{self.min_pump_percent}%)")
                logger.info(f"   📊 Filtered: {filtered_low_volume} low volume, {filtered_blacklist} blacklisted")
                for coin in pumped[:5]:  # Log top 5
                    vol_m = coin['volume'] / 1_000_000
                    logger.info(f"   {coin['symbol']}: +{coin['pump_percent']:.1f}% (Vol: ${vol_m:.1f}M)")
            
            return pumped
            
        except Exception as e:
            logger.error(f"Pump detection failed: {e}")
            return []
    
    def get_rsi(self, df) -> float:
        """Calculate current RSI from dataframe"""
        try:
            from indicators import calculate_rsi
            rsi = calculate_rsi(df['close'], getattr(config, 'RSI_PERIOD', 14))
            return float(rsi.iloc[-1])
        except:
            return 50
    
    def is_entry_ready(self, symbol: str, df) -> Dict:
        """
        Check if a pumped coin is ready for SHORT entry
        
        Conditions:
        - RSI > 75 (overbought)
        - OR RSI divergence (price up, RSI down)
        - OR candlestick reversal pattern
        
        Returns:
            Dict with ready: bool, reason: str, rsi: float
        """
        try:
            rsi = self.get_rsi(df)
            
            # Condition 1: Extreme overbought
            if rsi > 75:
                return {
                    'ready': True,
                    'reason': f'RSI Overbought ({rsi:.1f})',
                    'rsi': rsi,
                    'strength': 'strong'
                }
            
            # Condition 2: Near overbought with volume decline
            if rsi > 65:
                # Check if volume is declining (exhaustion)
                recent_volume = df['volume'].tail(3).mean()
                prev_volume = df['volume'].tail(10).head(7).mean()
                
                if recent_volume < prev_volume * 0.7:  # 30% volume drop
                    return {
                        'ready': True,
                        'reason': f'RSI {rsi:.1f} + Volume Exhaustion',
                        'rsi': rsi,
                        'strength': 'medium'
                    }
            
            # Condition 3: Check for reversal candle patterns
            last_candle = df.iloc[-1]
            prev_candle = df.iloc[-2]
            
            body = abs(last_candle['close'] - last_candle['open'])
            wick_top = last_candle['high'] - max(last_candle['close'], last_candle['open'])
            wick_bottom = min(last_candle['close'], last_candle['open']) - last_candle['low']
            
            # Shooting star / doji at top
            if wick_top > body * 2 and rsi > 60:
                return {
                    'ready': True,
                    'reason': f'Shooting Star + RSI {rsi:.1f}',
                    'rsi': rsi,
                    'strength': 'medium'
                }
            
            # Bearish engulfing
            if (last_candle['close'] < last_candle['open'] and  # Red candle
                prev_candle['close'] > prev_candle['open'] and  # Previous green
                last_candle['open'] > prev_candle['close'] and  # Opens above
                last_candle['close'] < prev_candle['open'] and  # Closes below
                rsi > 55):
                return {
                    'ready': True,
                    'reason': f'Bearish Engulfing + RSI {rsi:.1f}',
                    'rsi': rsi,
                    'strength': 'strong'
                }
            
            return {
                'ready': False,
                'reason': f'RSI {rsi:.1f} - Waiting for overbought',
                'rsi': rsi,
                'strength': None
            }
            
        except Exception as e:
            logger.debug(f"Entry check failed for {symbol}: {e}")
            return {'ready': False, 'reason': str(e), 'rsi': 50, 'strength': None}
    
    def get_pumped_coin(self, symbol: str) -> Optional[Dict]:
        """Get specific pumped coin data"""
        for coin in self.pumped_coins:
            if coin['symbol'] == symbol:
                return coin
        return None
    
    def check_1h_trend(self, symbol: str) -> Dict:
        """
        Check 1h timeframe for trend confirmation
        
        For counter-trend SHORT strategy:
        - If 1h RSI > 70: Good for SHORT (overbought on higher TF)
        - If 1h RSI > 60 + price near resistance: OK for SHORT
        - If 1h RSI < 50: Skip SHORT (still in uptrend)
        
        Returns:
            Dict with ok_to_short, reason, rsi_1h
        """
        try:
            # Get 1h klines
            klines = self.client.get_klines(symbol, '1h', limit=50)
            
            if not klines or len(klines) < 20:
                return {
                    'ok_to_short': True,  # Default to allow if data missing
                    'reason': 'No 1h data',
                    'rsi_1h': 50
                }
            
            import pandas as pd
            from indicators import calculate_rsi
            
            # Binance returns 12 columns for klines
            columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 
                      'close_time', 'quote_volume', 'trades', 'taker_buy_volume', 
                      'taker_buy_quote_volume', 'ignore']
            df = pd.DataFrame(klines, columns=columns)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            rsi_1h = calculate_rsi(df['close'], 14)
            current_rsi = float(rsi_1h.iloc[-1])
            
            # Check EMA for trend
            ema_9 = df['close'].ewm(span=9).mean().iloc[-1]
            ema_21 = df['close'].ewm(span=21).mean().iloc[-1]
            current_price = df['close'].iloc[-1]
            
            # Strong overbought on 1h - BEST for SHORT
            if current_rsi > 70:
                return {
                    'ok_to_short': True,
                    'reason': f'1h RSI {current_rsi:.0f} - Overbought ✅',
                    'rsi_1h': current_rsi,
                    'strength': 'strong'
                }
            
            # Moderately overbought + price extended
            if current_rsi > 60 and current_price > ema_9 * 1.02:
                return {
                    'ok_to_short': True,
                    'reason': f'1h RSI {current_rsi:.0f} + Extended',
                    'rsi_1h': current_rsi,
                    'strength': 'medium'
                }
            
            # Neutral RSI but price far above EMAs (exhaustion)
            if current_rsi > 50 and current_price > ema_21 * 1.05:
                return {
                    'ok_to_short': True,
                    'reason': f'1h RSI {current_rsi:.0f} + Far Extended',
                    'rsi_1h': current_rsi,
                    'strength': 'weak'
                }
            
            # RSI still low - uptrend may continue
            return {
                'ok_to_short': False,
                'reason': f'1h RSI {current_rsi:.0f} - Uptrend active ⚠️',
                'rsi_1h': current_rsi,
                'strength': None
            }
            
        except Exception as e:
            logger.debug(f"1h trend check failed for {symbol}: {e}")
            return {
                'ok_to_short': True,  # Default allow on error
                'reason': f'Check failed: {e}',
                'rsi_1h': 50
            }


if __name__ == "__main__":
    print("Pump Detector module loaded successfully!")
