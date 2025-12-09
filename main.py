"""
Multi-Timeframe Scalping Bot for Binance Futures
Main entry point with 10-second scanning loop
"""

import sys
import time
import signal as sig
from datetime import datetime, timezone

import config
from binance_client import BinanceClient
from scanner import Scanner
from strategy import Signal
from risk_manager import RiskManager
from order_executor import OrderExecutor
from position_monitor import PositionMonitor
from logger import (
    logger, print_banner, print_scan_header, 
    print_position_summary, log_signal
)

# Grok AI import (optional)
try:
    from grok_client import GrokClient
    GROK_AVAILABLE = True
except ImportError:
    GROK_AVAILABLE = False


class ScalpingBot:
    """Main bot controller"""
    
    def __init__(self):
        self.running = False
        self.scan_count = 0
        
        # Initialize components
        logger.info("Initializing bot components...")
        
        self.client = BinanceClient()
        self.scanner = Scanner(self.client)
        self.risk_manager = RiskManager(self.client)
        self.executor = OrderExecutor(self.client)
        self.position_monitor = PositionMonitor(self.client)
        
        # Initialize Grok AI if enabled
        self.grok = None
        if GROK_AVAILABLE and getattr(config, 'GROK_ENABLED', False):
            self.grok = GrokClient()
            logger.info("🤖 Grok AI enabled")
        
        # Initialize Chart Vision if enabled
        self.chart_vision = None
        if getattr(config, 'VISION_ENABLED', False):
            try:
                from chart_vision import ChartVision
                self.chart_vision = ChartVision(self.grok)
                logger.info("📊 Chart Vision enabled")
            except ImportError as e:
                logger.warning(f"Chart Vision not available: {e}")
        
        # State tracking
        self.last_scan_time = 0
        self.trades_today = 0
        self.signals_detected = 0
        
        # Daily Loss Limit tracking
        self.daily_start_balance = 0
        self.daily_loss_exceeded = False
        self.current_day = None
        
        # Grok tracking
        self.last_regime_check = 0
        self.last_news_check = None
        
        # Vision tracking
        self.last_vision_check = 0
        
        logger.info("Bot initialized successfully!")
    
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
            
            # Initialize daily loss tracking
            from datetime import datetime, timezone
            self.daily_start_balance = balance
            self.current_day = datetime.now(timezone.utc).date()
            self.daily_loss_exceeded = False
            
            if balance < 10:
                logger.warning("⚠️ Low balance! Minimum recommended: 10 USDT")
            
            # Load trading pairs (by volatility if enabled)
            pairs = self.scanner.smart_update_pairs()
            logger.info(f"✅ Loaded {len(pairs)} trading pairs")
            
            # Run initial Vision analysis so first trades can use it
            if self.chart_vision and pairs:
                logger.info("🤖 Running initial Vision analysis...")
                self.last_vision_check = 0  # Force run
                self._run_vision_analysis()
            
            # Check open positions
            positions = self.client.get_positions()
            logger.info(f"✅ Open positions: {len(positions)}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Startup check failed: {e}")
            return False
    
    def process_signal(self, signal: Signal) -> bool:
        """
        Process a trading signal
        
        Args:
            signal: Signal object
        
        Returns:
            True if trade was executed
        """
        self.signals_detected += 1
        
        # Log signal
        log_signal(signal.symbol, signal.type, signal.strength, signal.price)
        
        # Check if we can open new position
        positions = self.client.get_positions()
        
        if not self.risk_manager.can_open_position(positions):
            logger.info(f"⚠️ Max positions reached ({config.MAX_OPEN_POSITIONS})")
            return False
        
        # Check if already in this symbol
        if self.risk_manager.is_symbol_in_position(signal.symbol, positions):
            logger.debug(f"Already in position for {signal.symbol}")
            return False
        
        # Grok AI filter - check market regime
        if self.grok and not self.grok.should_trade_symbol(signal.symbol, signal.type):
            logger.info(f"🤖 Grok: Skipping {signal.type} {signal.symbol} (market regime)")
            return False
        
        # Get Support/Resistance levels for smart SL/TP
        sr_levels = None
        try:
            from indicators import find_support_resistance
            klines_15m = self.client.get_klines(signal.symbol, config.TREND_TIMEFRAME, limit=100)
            if klines_15m:
                import pandas as pd
                df = pd.DataFrame(klines_15m)
                sr_levels = find_support_resistance(df['high'], df['low'], df['close'])
                if sr_levels and sr_levels.get('nearest_support'):
                    logger.debug(f"📊 S/R: Support={sr_levels['nearest_support']:.4f}, Resistance={sr_levels.get('nearest_resistance', 'N/A')}")
        except Exception as e:
            logger.debug(f"S/R detection failed: {e}")
        
        # Calculate trade parameters (uses fixed capital from config)
        trade_params = self.risk_manager.calculate_trade_params(
            symbol=signal.symbol,
            side=signal.type,
            entry_price=signal.price,
            atr=signal.indicators.get('atr', signal.price * 0.01),
            sr_levels=sr_levels
        )
        
        # Override with Vision SL/TP if available and confident
        vision_data = None
        if self.chart_vision:
            vision_data = self.chart_vision.get_vision_sl_tp(
                signal.symbol, signal.type, signal.price
            )
            
            # Vision Signal Confirm - must match indicator signal
            if getattr(config, 'VISION_REQUIRE_CONFIRM', False):
                vision_signal = vision_data.get('signal', 'WAIT')
                if vision_signal and vision_signal != 'WAIT':
                    if (signal.type == 'BUY' and vision_signal != 'BUY') or \
                       (signal.type == 'SELL' and vision_signal != 'SELL'):
                        logger.info(f"❌ Vision Reject: Signal {signal.type} != Vision {vision_signal}")
                        return False
            
            # Vision SL/TP Required
            if getattr(config, 'VISION_REQUIRE_SL_TP', False):
                if not vision_data.get('vision_used'):
                    logger.info(f"❌ Vision Reject: No SL/TP from Vision for {signal.symbol}")
                    return False
            
            # Use Vision SL/TP if available
            if vision_data.get('vision_used'):
                if vision_data.get('stop_loss'):
                    trade_params['stop_loss'] = self.client.round_price(
                        signal.symbol, vision_data['stop_loss']
                    )
                if vision_data.get('take_profit'):
                    trade_params['take_profit'] = self.client.round_price(
                        signal.symbol, vision_data['take_profit']
                    )
                logger.info(f"✅ Vision Confirm: {signal.type} | Pattern={vision_data.get('pattern', 'N/A')} | Conf={vision_data.get('confidence', 0)}%")
        
        # Validate trade
        is_valid, reason = self.risk_manager.validate_trade(trade_params)
        if not is_valid:
            logger.warning(f"Trade validation failed: {reason}")
            return False
        
        # Execute trade
        logger.info(f"🚀 Executing trade: {signal.symbol} {signal.type}")
        logger.info(f"   Entry: {signal.price:.4f} | SL: {trade_params['stop_loss']:.4f} | TP: {trade_params['take_profit']:.4f}")
        logger.info(f"   Quantity: {trade_params['quantity']} | Margin: ${trade_params['initial_margin']:.2f} | Risk: ${trade_params['risk_usdt']:.2f}")
        
        result = self.executor.execute_entry(trade_params)
        
        if result:
            self.trades_today += 1
            logger.info(f"✅ Trade executed successfully!")
            return True
        else:
            logger.error(f"❌ Trade execution failed")
            return False
    
    def _check_daily_loss_limit(self):
        """Check if daily loss limit has been exceeded"""
        from datetime import datetime, timezone
        
        today = datetime.now(timezone.utc).date()
        
        # Reset at new day
        if self.current_day != today:
            self.current_day = today
            self.daily_start_balance = self.client.get_usdt_balance()
            self.daily_loss_exceeded = False
            logger.info(f"📅 New trading day - balance reset to {self.daily_start_balance:.2f}")
            return
        
        # Check current balance vs start
        current_balance = self.client.get_usdt_balance()
        if self.daily_start_balance > 0:
            loss_percent = ((self.daily_start_balance - current_balance) / self.daily_start_balance) * 100
            
            max_loss = getattr(config, 'MAX_DAILY_LOSS_PERCENT', 5.0)
            if loss_percent >= max_loss:
                if not self.daily_loss_exceeded:
                    logger.error(f"⛔ Daily loss limit reached: {loss_percent:.2f}% (max: {max_loss}%)")
                self.daily_loss_exceeded = True
    
    def _check_grok_updates(self):
        """Check if Grok analysis needs to be updated"""
        if not self.grok:
            return
        
        current_time = time.time()
        
        # Market regime check every 30 minutes
        regime_interval = getattr(config, 'GROK_MARKET_REGIME_INTERVAL', 30) * 60
        if current_time - self.last_regime_check >= regime_interval:
            self.last_regime_check = current_time
            
            # Get market data for analysis
            try:
                tickers = self.client.get_ticker_24h()
                btc = next((t for t in tickers if t['symbol'] == 'BTCUSDT'), {})
                eth = next((t for t in tickers if t['symbol'] == 'ETHUSDT'), {})
                
                # Get top gainers/losers
                sorted_tickers = sorted(tickers, key=lambda x: float(x.get('priceChangePercent', 0)), reverse=True)
                top_gainers = [f"{t['symbol']} {float(t['priceChangePercent']):.1f}%" for t in sorted_tickers[:3]]
                top_losers = [f"{t['symbol']} {float(t['priceChangePercent']):.1f}%" for t in sorted_tickers[-3:]]
                
                market_data = {
                    'btc_change': float(btc.get('priceChangePercent', 0)),
                    'eth_change': float(eth.get('priceChangePercent', 0)),
                    'top_gainers': top_gainers,
                    'top_losers': top_losers,
                    'sentiment': 'Neutral'
                }
                
                self.grok.analyze_market_regime(market_data)
            except Exception as e:
                logger.debug(f"Grok regime check failed: {e}")
        
        # Daily news check
        now = datetime.now(timezone.utc)
        news_hour = getattr(config, 'GROK_NEWS_ANALYSIS_HOUR', 8)
        
        if self.last_news_check is None or self.last_news_check.date() != now.date():
            if now.hour >= news_hour:
                self.last_news_check = now
                try:
                    self.grok.analyze_news_sentiment()
                except Exception as e:
                    logger.debug(f"Grok news check failed: {e}")
    
    def _run_vision_analysis(self):
        """Run vision analysis on top pairs every 3 minutes"""
        if not self.chart_vision:
            return
        
        current_time = time.time()
        interval = getattr(config, 'VISION_ANALYSIS_INTERVAL', 3) * 60
        
        if current_time - self.last_vision_check < interval:
            return
        
        self.last_vision_check = current_time
        logger.info("🤖 Running Vision Analysis on top 10 pairs...")
        
        # Analyze top 10 pairs from our list (reduced from 15 to save API cost)
        pairs_to_analyze = self.scanner.pairs[:10] if self.scanner.pairs else []
        
        for symbol in pairs_to_analyze:
            try:
                # Get klines for chart
                klines = self.client.get_klines(symbol, config.TREND_TIMEFRAME, limit=100)
                if not klines:
                    continue
                
                import pandas as pd
                from indicators import calculate_ema, calculate_rsi, calculate_bollinger_bands
                
                # Add column names for klines data
                columns = ['open_time', 'open', 'high', 'low', 'close', 'volume', 
                          'close_time', 'quote_volume', 'trades', 'taker_buy_volume', 
                          'taker_buy_quote_volume', 'ignore']
                df = pd.DataFrame(klines, columns=columns)
                
                # Convert to float
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                
                # Add all indicators for better chart
                df['ema_fast'] = calculate_ema(df['close'], config.EMA_FAST_PERIOD)
                df['ema_slow'] = calculate_ema(df['close'], config.EMA_SLOW_PERIOD)
                df['rsi'] = calculate_rsi(df['close'], config.RSI_PERIOD)
                
                # Bollinger Bands
                bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(df['close'])
                df['bb_upper'] = bb_upper
                df['bb_middle'] = bb_middle
                df['bb_lower'] = bb_lower
                
                # Generate chart
                chart_base64 = self.chart_vision.generate_chart(symbol, df, config.TREND_TIMEFRAME)
                
                if chart_base64:
                    current_price = float(df['close'].iloc[-1])
                    # Use enhanced analysis method
                    self.chart_vision.analyze_chart_with_vision(symbol, chart_base64, current_price)
                    
            except Exception as e:
                logger.error(f"Vision chart failed for {symbol}: {e}")
    
    def run_scan_cycle(self):
        """Run a single scan cycle"""
        self.scan_count += 1
        
        # Check daily loss limit
        if getattr(config, 'DAILY_LOSS_LIMIT_ENABLED', False):
            self._check_daily_loss_limit()
            if self.daily_loss_exceeded:
                if self.scan_count % 30 == 0:  # Log every 30 scans
                    logger.warning("⛔ Daily loss limit exceeded - trading paused")
                return
        
        # Grok AI checks
        self._check_grok_updates()
        
        # Vision analysis (every 3 minutes)
        self._run_vision_analysis()
        
        # Check if we need to refresh pairs by volatility
        if self.scanner.should_refresh_volatility():
            self.scanner.smart_update_pairs()
        
        # Print scan header
        print_scan_header(self.scan_count, len(self.scanner.pairs))
        
        # Get current positions
        try:
            positions = self.client.get_positions()
            print_position_summary(positions)
            
            # Check partial take profit and update trailing stops
            for pos in positions:
                symbol = pos['symbol']
                current_price = float(pos.get('markPrice', 0))
                if current_price > 0:
                    self.position_monitor.check_partial_take_profit(symbol, current_price)
            
            # Update trailing stops
            updated = self.position_monitor.update_trailing_stops(positions)
            if updated > 0:
                logger.info(f"🔄 Updated {updated} trailing stop(s)")
        except Exception as e:
            logger.debug(f"Error getting positions: {e}")
            positions = []
        
        # Scan for signals
        signals = self.scanner.scan_all_pairs_threaded()
        
        if not signals:
            logger.info("No valid signals found")
            return
        
        # Process best signal(s)
        for signal in signals[:2]:  # Process top 2 signals max
            if self.risk_manager.can_open_position(positions):
                self.process_signal(signal)
                # Refresh positions after trade
                positions = self.client.get_positions()
    
    def run(self):
        """Main bot loop"""
        self.running = True
        
        # Print banner
        print_banner()
        
        # Startup checks
        if not self.startup_checks():
            logger.error("Startup checks failed. Exiting.")
            return
        
        logger.info(f"🚀 Starting main loop (interval: {config.SCAN_INTERVAL_SECONDS}s)")
        logger.info("Press Ctrl+C to stop\n")
        
        try:
            while self.running:
                cycle_start = time.time()
                
                # Run scan cycle
                try:
                    self.run_scan_cycle()
                except Exception as e:
                    logger.error(f"Scan cycle error: {e}")
                
                # Calculate sleep time
                cycle_duration = time.time() - cycle_start
                sleep_time = max(0, config.SCAN_INTERVAL_SECONDS - cycle_duration)
                
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    
        except KeyboardInterrupt:
            logger.info("\n⏹️ Stopping bot...")
            self.stop()
    
    def stop(self):
        """Stop the bot gracefully"""
        self.running = False
        
        # Print summary
        logger.info("\n" + "="*50)
        logger.info("📊 Session Summary:")
        logger.info(f"   Total Scans: {self.scan_count}")
        logger.info(f"   Signals Detected: {self.signals_detected}")
        logger.info(f"   Trades Executed: {self.trades_today}")
        logger.info("="*50)
        
        # Ask about closing positions
        try:
            positions = self.client.get_positions()
            if positions:
                logger.warning(f"⚠️ {len(positions)} open positions remaining")
        except:
            pass
        
        logger.info("👋 Bot stopped. Goodbye!")


def main():
    """Entry point"""
    
    # Handle Ctrl+C gracefully
    def signal_handler(signum, frame):
        print("\n")
        sys.exit(0)
    
    sig.signal(sig.SIGINT, signal_handler)
    
    # Create and run bot
    bot = ScalpingBot()
    bot.run()


if __name__ == "__main__":
    main()
