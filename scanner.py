"""
Multi-Pair Scanner Module
Scans top 30 pairs for trading signals
"""

import asyncio
import aiohttp
import time
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

import config
from binance_client import BinanceClient
from indicators import klines_to_dataframe, calculate_all_indicators, get_latest_indicators
from strategy import generate_signal, filter_signals, Signal
from logger import logger


class Scanner:
    """Scans multiple trading pairs for signals"""
    
    def __init__(self, client: BinanceClient):
        self.client = client
        self.pairs = []
        self.last_scan_time = 0
        self.scan_count = 0
        
        # Volatility refresh tracking
        self.last_volatility_refresh = 0
        
        # Cache for kline data
        self._kline_cache = {}
        self._cache_expiry = 5  # seconds
    
    def update_pairs(self) -> List[str]:
        """Fetch and update top trading pairs by volume (fallback)"""
        try:
            self.pairs = self.client.get_top_pairs_by_volume(config.TOP_PAIRS_COUNT)
            logger.info(f"Updated pairs list: {len(self.pairs)} pairs (by volume)")
            return self.pairs
        except Exception as e:
            logger.error(f"Failed to update pairs: {e}")
            return self.pairs
    
    def update_pairs_by_volatility(self) -> List[str]:
        """Fetch and update top trading pairs by volatility"""
        try:
            self.pairs = self.client.get_top_pairs_by_volatility(config.TOP_PAIRS_COUNT)
            self.last_volatility_refresh = time.time()
            logger.info(f"🔥 Updated pairs list: {len(self.pairs)} pairs (by volatility)")
            return self.pairs
        except Exception as e:
            logger.error(f"Failed to update pairs by volatility: {e}")
            # Fallback to volume-based
            return self.update_pairs()
    
    def should_refresh_volatility(self) -> bool:
        """Check if it's time to refresh volatility pairs"""
        if not getattr(config, 'USE_VOLATILITY_RANKING', False):
            return False
        
        refresh_interval = getattr(config, 'VOLATILITY_REFRESH_MINUTES', 5) * 60
        elapsed = time.time() - self.last_volatility_refresh
        return elapsed >= refresh_interval
    
    def smart_update_pairs(self) -> List[str]:
        """Smart pair update - uses volatility if enabled, else volume"""
        if getattr(config, 'USE_VOLATILITY_RANKING', False):
            if self.should_refresh_volatility() or len(self.pairs) == 0:
                return self.update_pairs_by_volatility()
            return self.pairs
        else:
            return self.update_pairs()
    
    def fetch_klines_for_symbol(self, symbol: str, interval: str) -> Optional[Dict]:
        """
        Fetch and process klines for a single symbol
        
        Returns:
            Dictionary with indicators or None
        """
        try:
            # Check cache
            cache_key = f"{symbol}_{interval}"
            if cache_key in self._kline_cache:
                cache_time, data = self._kline_cache[cache_key]
                if time.time() - cache_time < self._cache_expiry:
                    return data
            
            # Fetch klines
            klines = self.client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=config.KLINES_LIMIT
            )
            
            if not klines:
                return None
            
            # Convert to DataFrame and calculate indicators
            df = klines_to_dataframe(klines)
            df = calculate_all_indicators(df)
            indicators = get_latest_indicators(df)
            
            # Cache result
            self._kline_cache[cache_key] = (time.time(), indicators)
            
            return indicators
            
        except Exception as e:
            logger.debug(f"Error fetching {symbol} {interval}: {e}")
            return None
    
    def scan_symbol(self, symbol: str) -> Optional[Signal]:
        """
        Perform full analysis on a single symbol using triple timeframe
        
        Returns:
            Signal object or None
        """
        # Get primary timeframe (1m)
        primary = self.fetch_klines_for_symbol(symbol, config.PRIMARY_TIMEFRAME)
        if not primary:
            return None
        
        # Get confirmation timeframe (5m)
        confirmation = None
        if config.REQUIRE_CONFIRMATION:
            confirmation = self.fetch_klines_for_symbol(
                symbol, config.CONFIRMATION_TIMEFRAME
            )
        
        # Get trend timeframe (15m) - medium-term trend
        trend = None
        if hasattr(config, 'TREND_TIMEFRAME'):
            trend = self.fetch_klines_for_symbol(
                symbol, config.TREND_TIMEFRAME
            )
        
        # Get macro timeframe (30m) - main trend direction
        macro = None
        if hasattr(config, 'MACRO_TIMEFRAME'):
            macro = self.fetch_klines_for_symbol(
                symbol, config.MACRO_TIMEFRAME
            )
        
        # Get major timeframe (1h) - major trend direction
        major = None
        if hasattr(config, 'MAJOR_TIMEFRAME'):
            major = self.fetch_klines_for_symbol(
                symbol, config.MAJOR_TIMEFRAME
            )
        
        # Generate signal with 5 timeframes
        signal = generate_signal(symbol, primary, confirmation, trend, macro, major)
        
        return signal
    
    def scan_all_pairs(self) -> List[Signal]:
        """
        Scan all pairs and return signals
        
        Returns:
            List of valid signals sorted by strength
        """
        self.scan_count += 1
        self.last_scan_time = time.time()
        
        signals = []
        
        for symbol in self.pairs:
            try:
                signal = self.scan_symbol(symbol)
                if signal and signal.type != Signal.NEUTRAL:
                    signals.append(signal)
                    
                    # Log signal
                    if signal.is_valid():
                        logger.info(
                            f"📊 {symbol}: {signal.type} | "
                            f"Strength: {signal.strength}/5 | "
                            f"Price: {signal.price:.4f}"
                        )
            except Exception as e:
                logger.debug(f"Error scanning {symbol}: {e}")
                continue
        
        # Filter and sort by strength
        valid_signals = filter_signals(signals)
        
        return valid_signals
    
    def scan_all_pairs_threaded(self) -> List[Signal]:
        """
        Scan all pairs using thread pool for better performance
        
        Returns:
            List of valid signals sorted by strength
        """
        self.scan_count += 1
        self.last_scan_time = time.time()
        
        signals = []
        
        # Use thread pool for concurrent requests
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self.scan_symbol, symbol): symbol 
                for symbol in self.pairs
            }
            
            for future in futures:
                try:
                    signal = future.result(timeout=5)
                    if signal and signal.type != Signal.NEUTRAL:
                        signals.append(signal)
                except Exception as e:
                    logger.debug(f"Thread error: {e}")
                    continue
        
        # Filter and sort
        valid_signals = filter_signals(signals)
        
        # Log summary
        buy_count = len([s for s in valid_signals if s.type == Signal.BUY])
        sell_count = len([s for s in valid_signals if s.type == Signal.SELL])
        logger.info(f"Scan #{self.scan_count}: Found {buy_count} BUY, {sell_count} SELL signals")
        
        return valid_signals
    
    def get_best_signal(self) -> Optional[Signal]:
        """
        Get the single best trading signal
        
        Returns:
            Best signal or None
        """
        signals = self.scan_all_pairs_threaded()
        
        if signals:
            return signals[0]
        return None
    
    def clear_cache(self):
        """Clear the kline cache"""
        self._kline_cache.clear()
    
    def get_stats(self) -> Dict:
        """Get scanner statistics"""
        return {
            'pairs_count': len(self.pairs),
            'scan_count': self.scan_count,
            'last_scan': self.last_scan_time,
            'cache_size': len(self._kline_cache)
        }


# Test when run directly
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Run in test mode')
    args = parser.parse_args()
    
    print("Testing Scanner Module...")
    
    client = BinanceClient()
    scanner = Scanner(client)
    
    # Get top pairs
    pairs = scanner.update_pairs()
    print(f"✅ Loaded {len(pairs)} pairs")
    print(f"Top 5: {pairs[:5]}")
    
    if args.test or True:
        # Run single scan
        print("\n📊 Running scan...")
        signals = scanner.scan_all_pairs_threaded()
        
        print(f"\n✅ Found {len(signals)} valid signals:")
        for signal in signals[:5]:
            print(f"  {signal.symbol}: {signal.type} (strength: {signal.strength})")
        
        # Stats
        stats = scanner.get_stats()
        print(f"\n📈 Stats: {stats}")
