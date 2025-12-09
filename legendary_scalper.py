"""
Legendary Martingale Scalper - Counter-Trend SHORT Strategy

╔══════════════════════════════════════════════════════════════╗
║  🎰 LEGENDARY MARTINGALE SCALPER 🎰                          ║
║                                                              ║
║  Strategy: Counter-Trend Martingale SHORT                   ║
║  Target: Highly Pumped Coins (20%+)                         ║
║                                                              ║
║  "The bot hunts like an eagle"                              ║
╚══════════════════════════════════════════════════════════════╝

Finds pumped coins (20%+) and shorts on exhaustion signals
"""

import sys
import time
import signal as sig
from datetime import datetime, timezone

import config
from binance_client import BinanceClient
from order_executor import OrderExecutor
from pump_detector import PumpDetector
from martingale_manager import MartingaleManager
from position_watcher import PositionWatcher
from grok_client import GrokClient
from logger import logger


class LegendaryScalper:
    """
    Counter-trend Martingale scalper
    
    Strategy:
    1. Find coins pumped >30% in 24h
    2. Wait for exhaustion signals (RSI overbought, volume decline)
    3. Enter SHORT with small margin
    4. Add steps as price goes higher (averaging up)
    5. Close half when price returns to average
    6. Take full profit on reversal
    """
    
    def __init__(self):
        self.running = False
        
        logger.info("🎰 Initializing Legendary Scalper...")
        
        # Core components
        self.client = BinanceClient()
        self.executor = OrderExecutor(self.client)
        
        # Martingale components
        self.pump_detector = PumpDetector(self.client)
        self.martingale = MartingaleManager(self.client, self.executor)
        self.watcher = PositionWatcher(self.client, self.martingale, self.pump_detector)
        
        # Grok AI for sentiment analysis
        self.grok = GrokClient() if getattr(config, 'GROK_ENABLED', True) else None
        
        # Tracking
        self.scan_count = 0
        self.last_pump_scan = 0
        self.pump_scan_interval = 90  # Scan for pumps every 90 seconds
        
        logger.info("✅ Legendary Scalper initialized!")
        self._print_config()
    
    def _print_config(self):
        """Print configuration summary"""
        logger.info("📊 Configuration:")
        logger.info(f"   Min Pump: {config.MARTINGALE_MIN_PUMP}%")
        logger.info(f"   Max Positions: {config.MARTINGALE_MAX_POSITIONS}")
        logger.info(f"   Steps: {config.MARTINGALE_STEPS}")
        logger.info(f"   Total Max Margin: ${sum(config.MARTINGALE_STEPS)}")
    
    def startup_checks(self) -> bool:
        """Perform startup checks"""
        logger.info("Running startup checks...")
        
        try:
            # Test API connection
            server_time = self.client.get_server_time()
            logger.info(f"✅ API Connected (Server time: {server_time})")
            
            # Check balance
            balance = self.client.get_usdt_balance()
            logger.info(f"✅ USDT Balance: {balance:.2f}")
            
            if balance < sum(config.MARTINGALE_STEPS):
                logger.warning(f"⚠️ Balance may be insufficient for full Martingale")
            
            # Recover existing positions from Binance
            logger.info("♻️ Checking for existing positions...")
            recovered = self.martingale.recover_positions()
            if recovered > 0:
                logger.info(f"✅ Recovered {recovered} positions - will continue managing them!")
            
            # Initial pump scan
            logger.info("🔍 Scanning for pumped coins...")
            pumped = self.pump_detector.find_pumped_coins()
            logger.info(f"✅ Found {len(pumped)} coins with >{config.MARTINGALE_MIN_PUMP}% pump")
            
            return True
            
        except Exception as e:
            logger.error(f"Startup check failed: {e}")
            return False
    
    def run_cycle(self):
        """Run a single scan cycle"""
        self.scan_count += 1
        current_time = time.time()
        
        # 1. Check existing positions (always)
        logger.info(f"📊 Cycle #{self.scan_count} | Checking positions...")
        actions = self.watcher.check_positions()
        
        if actions['steps_added']:
            for sym in actions['steps_added']:
                logger.info(f"🎰 Added step for {sym}")
        
        if actions['half_closed']:
            for sym in actions['half_closed']:
                logger.info(f"✂️ Half-closed {sym}")
        
        if actions['closed']:
            for sym in actions['closed']:
                logger.info(f"💰 Closed {sym}")
        
        if actions['emergency_closed']:
            for sym in actions['emergency_closed']:
                logger.warning(f"🚨 Emergency closed {sym}")
        
        # 2. Scan for new opportunities (every pump_scan_interval)
        if current_time - self.last_pump_scan >= self.pump_scan_interval:
            self.last_pump_scan = current_time
            
            opportunities = self.watcher.scan_for_new_entries()
            
            for opp in opportunities[:5]:  # Open up to 5 positions per scan
                if self.martingale.can_open_new_position():
                    symbol = opp['symbol']
                    pump = opp['pump']
                    
                    # Check 1h trend for multi-timeframe confirmation
                    trend_check = self.pump_detector.check_1h_trend(symbol)
                    if not trend_check.get('ok_to_short', True):
                        logger.info(f"⏭️ Skipping {symbol} - {trend_check.get('reason')}")
                        continue
                    logger.info(f"📊 1h Check: {symbol} - {trend_check.get('reason')}")
                    
                    # Check Grok sentiment for high pumps
                    if self.grok and pump >= 40:
                        sentiment = self.grok.is_good_short_entry(symbol, pump)
                        if not sentiment.get('is_good', True):
                            logger.info(f"⏭️ Skipping {symbol} - Grok: {sentiment.get('reason')}")
                            continue
                        logger.info(f"🤖 Grok: {symbol} FOMO {sentiment.get('fomo_level', 0)}%")
                    
                    logger.info(f"🎯 Opening SHORT: {symbol} (Pump: +{pump:.1f}%)")
                    self.martingale.open_position(symbol, opp['price'])
        
        # 3. Log status
        self.watcher.log_status()
    
    def run(self):
        """Main loop"""
        if not self.startup_checks():
            logger.error("Startup failed!")
            return
        
        self.running = True
        
        # Print banner
        print("\n" + "="*65)
        print("🎰 LEGENDARY MARTINGALE SCALPER 🎰")
        print("="*65)
        print("Strategy: Counter-Trend SHORT on Pumped Coins")
        print(f"Min Pump: {config.MARTINGALE_MIN_PUMP}%")
        print(f"Max Margin: ${sum(config.MARTINGALE_STEPS)}")
        print(f"Mode: {'TESTNET' if config.USE_TESTNET else 'PRODUCTION'}")
        print("="*65 + "\n")
        
        logger.info("🚀 Starting main loop...")
        logger.info("Press Ctrl+C to stop")
        
        try:
            while self.running:
                self.run_cycle()
                time.sleep(20)  # Check every 20 seconds
                
        except KeyboardInterrupt:
            logger.info("⛔ Stopping bot...")
            self.stop()
    
    def stop(self):
        """Stop the bot"""
        self.running = False
        
        # Log final status
        status = self.martingale.get_status()
        logger.info(f"📊 Final Status: {status['active_positions']} open positions")
        
        for symbol, pos in status['positions'].items():
            logger.info(f"   {symbol}: Step {pos['step']}, Margin ${pos['total_margin']}")
        
        logger.info("👋 Bot stopped. Goodbye!")


def signal_handler(signum, frame):
    """Handle Ctrl+C"""
    logger.info("Received stop signal...")
    sys.exit(0)


if __name__ == "__main__":
    sig.signal(sig.SIGINT, signal_handler)
    
    bot = LegendaryScalper()
    bot.run()
