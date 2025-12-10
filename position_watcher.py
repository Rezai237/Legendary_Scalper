"""
Position Watcher - 24/7 monitoring of Martingale positions
"""

import time
from typing import Dict, Optional
from datetime import datetime
from logger import logger
import config


class PositionWatcher:
    """
    Watch Martingale positions and monitor for:
    - Step entry opportunities
    - Half-close opportunities
    - Emergency stops
    - Take profit
    """
    
    def __init__(self, client, martingale_manager, pump_detector):
        self.client = client
        self.martingale = martingale_manager
        self.pump_detector = pump_detector
        self.last_check = {}
        
        # Take profit settings
        self.take_profit_percent = getattr(config, 'MARTINGALE_TP_PERCENT', 1.5)
        
        logger.info("👁️ Position Watcher initialized")
    
    def check_positions(self) -> Dict:
        """
        Check all Martingale positions and take actions
        
        Returns:
            Dict with actions taken
        """
        actions = {
            'steps_added': [],
            'half_closed': [],
            'closed': [],
            'emergency_closed': []
        }
        
        # Get blacklist from config
        blacklist = getattr(config, 'BLACKLIST', [])
        
        for symbol, position in list(self.martingale.positions.items()):
            try:
                # Skip blacklisted symbols - they cause API errors
                if symbol in blacklist:
                    logger.warning(f"⏭️ Skipping blacklisted symbol: {symbol}")
                    continue
                
                # Get current price
                ticker = self.client.get_mark_price(symbol)
                if not ticker:
                    continue
                
                current_price = float(ticker.get('markPrice', 0))
                if current_price <= 0:
                    continue
                
                # 1. Check emergency stop - WARNING ONLY, no auto close
                emergency = self.martingale.should_emergency_close(symbol, current_price)
                if emergency.get('should_close'):
                    logger.warning(f"⚠️ HIGH DRAWDOWN WARNING: {symbol} - {emergency['reason']}")
                    # NO AUTO CLOSE - just warning, user will decide
                
                # 2. Check take profit
                tp_check = self._check_take_profit(position, current_price)
                if tp_check.get('should_close'):
                    logger.info(f"🎯 Take Profit: {tp_check['reason']}")
                    if self.martingale.close_position(symbol, current_price, "Take Profit"):
                        actions['closed'].append(symbol)
                    continue
                
                # 3. Check half-close opportunity
                half_close = self.martingale.should_close_half(symbol, current_price)
                if half_close.get('should_close'):
                    if self.martingale.close_half(symbol, current_price):
                        actions['half_closed'].append(symbol)
                    continue
                
                # 3a. Check auto-close early positions (step 1-3) when margin > $100
                auto_close = self.martingale.should_auto_close_early(symbol, current_price)
                if auto_close.get('should_close'):
                    if self.martingale.close_position(symbol, current_price):
                        if 'auto_closed' not in actions:
                            actions['auto_closed'] = []
                        actions['auto_closed'].append(symbol)
                        logger.info(f"🧹 Auto-closed {symbol} - {auto_close.get('reason')}")
                    continue
                
                # 3b. Check margin recycling opportunity (for extended steps)
                recycle = self.martingale.should_recycle_margin(symbol, current_price)
                if recycle.get('should_recycle'):
                    if self.martingale.recycle_margin(symbol, current_price):
                        if 'recycled' not in actions:
                            actions['recycled'] = []
                        actions['recycled'].append(symbol)
                    # Don't continue - allow adding more steps after recycling
                
                # 4. Check if should add step
                step_check = self.martingale.should_add_step(symbol, current_price)
                if step_check.get('should_add'):
                    # Get fresh data for entry confirmation
                    if self._confirm_step_entry(symbol, current_price, position.step + 1):
                        if self.martingale.add_step(symbol, current_price):
                            actions['steps_added'].append(symbol)
                
            except Exception as e:
                logger.error(f"Position check failed for {symbol}: {e}")
        
        return actions
    
    def _check_take_profit(self, position, current_price: float) -> Dict:
        """
        Check if position should take profit with TRAILING TP
        
        Dynamic TP activation threshold:
        - Step 1: $3.5 profit
        - Step 2: $4 profit
        - Step 3: $6 profit
        - Step 4: $8 profit
        - Step 5: $10 profit
        - Step 6-7: $12 profit
        - Step 8+: $20 profit
        
        Trailing TP:
        - Activates when profit >= threshold
        - Tracks max profit seen
        - Closes when profit drops 30% from max (even if below threshold)
        - Only resets if profit drops below $0.50
        """
        # Calculate actual P&L in USD
        pnl_usd = (position.average_entry - current_price) * position.total_quantity
        
        # Dynamic TP activation threshold based on step
        step = position.step
        if step <= 1:
            tp_target = 3.5  # Activate trailing at $3.5
        elif step == 2:
            tp_target = 4
        elif step == 3:
            tp_target = 6
        elif step == 4:
            tp_target = 8
        elif step == 5:
            tp_target = 10
        elif step <= 7:
            tp_target = 12
        else:  # step 8+
            tp_target = 20
        
        # TRAILING TP LOGIC
        trailing_callback = 0.30  # Close if profit drops 30% from max
        
        # CASE 1: Trailing is already active
        if position.trailing_tp_active:
            # Update max profit if current is higher
            if pnl_usd > position.max_profit_usd:
                position.max_profit_usd = pnl_usd
                logger.debug(f"📈 {position.symbol}: New max profit ${pnl_usd:.2f}")
            
            # Check for 30% callback from max (THIS RUNS EVEN IF BELOW TARGET)
            if position.max_profit_usd > 0:
                profit_drop_percent = (position.max_profit_usd - pnl_usd) / position.max_profit_usd
                
                if profit_drop_percent >= trailing_callback:
                    return {
                        'should_close': True,
                        'reason': f'Trailing TP hit (${pnl_usd:.2f}, max was ${position.max_profit_usd:.2f})',
                        'pnl_usd': pnl_usd,
                        'tp_target': tp_target,
                        'max_profit': position.max_profit_usd
                    }
            
            # Reset trailing only if profit drops very low (below $0.50)
            if pnl_usd < 0.50:
                position.trailing_tp_active = False
                position.max_profit_usd = 0
                logger.info(f"🔄 {position.symbol}: Trailing reset (profit ${pnl_usd:.2f})")
                return {'should_close': False, 'pnl_usd': pnl_usd, 'tp_target': tp_target}
            
            # Continue trailing
            return {
                'should_close': False, 
                'pnl_usd': pnl_usd, 
                'tp_target': tp_target,
                'trailing': True,
                'max_profit': position.max_profit_usd
            }
        
        # CASE 2: Trailing not yet active - check if should activate
        if pnl_usd >= tp_target:
            position.trailing_tp_active = True
            position.max_profit_usd = pnl_usd
            logger.info(f"🎯 {position.symbol}: Trailing TP activated at ${pnl_usd:.2f}")
            
            return {
                'should_close': False, 
                'pnl_usd': pnl_usd, 
                'tp_target': tp_target,
                'trailing': True,
                'max_profit': position.max_profit_usd
            }
        
        # CASE 3: Not trailing, not at target yet
        return {'should_close': False, 'pnl_usd': pnl_usd, 'tp_target': tp_target}
    
    def _confirm_step_entry(self, symbol: str, current_price: float, step_num: int) -> bool:
        """
        Confirm that it's a good time to add a step
        
        Steps 1-3: Quick entry (distance-based only)
        Steps 4+: Eagle-eye mode - wait for strong reversal signals
        """
        try:
            # Get klines for analysis
            klines = self.client.get_klines(symbol, '5m', 50)
            if not klines:
                return step_num <= 3  # Allow early steps without data
            
            import pandas as pd
            columns = ['open_time', 'open', 'high', 'low', 'close', 'volume', 
                      'close_time', 'quote_volume', 'trades', 'taker_buy_volume', 
                      'taker_buy_quote_volume', 'ignore']
            df = pd.DataFrame(klines, columns=columns)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            
            # Steps 1-3: Less strict, just check RSI
            if step_num <= 3:
                entry = self.pump_detector.is_entry_ready(symbol, df)
                return True  # Always allow if distance ok
            
            # 🦅 EAGLE-EYE MODE for Steps 4+ 🦅
            logger.info(f"🦅 Eagle-eye analysis for Step {step_num}...")
            
            # Get last candles
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            # 1. Check for PIN BAR (long upper wick = buyers exhausted)
            body = abs(last['close'] - last['open'])
            upper_wick = last['high'] - max(last['close'], last['open'])
            lower_wick = min(last['close'], last['open']) - last['low']
            total_range = last['high'] - last['low']
            
            has_pin_bar = upper_wick > body * 2 and upper_wick > total_range * 0.5
            if has_pin_bar:
                logger.info(f"   ✅ Pin Bar detected! Upper wick = {upper_wick:.6f}")
            
            # 2. Check for VOLUME EXHAUSTION (volume decreasing)
            recent_vol = df['volume'].tail(3).mean()
            prev_vol = df['volume'].tail(10).head(7).mean()
            volume_exhaustion = recent_vol < prev_vol * 0.7  # 30% drop
            if volume_exhaustion:
                logger.info(f"   ✅ Volume exhaustion! {recent_vol:.0f} < {prev_vol:.0f}")
            
            # 3. Check for BEARISH ENGULFING
            bearish_engulf = (
                last['close'] < last['open'] and  # Red candle
                prev['close'] > prev['open'] and  # Previous green
                last['open'] > prev['close'] and  # Opens above
                last['close'] < prev['open']       # Closes below
            )
            if bearish_engulf:
                logger.info(f"   ✅ Bearish Engulfing pattern!")
            
            # 4. Check RSI still high
            rsi = self.pump_detector.get_rsi(df)
            rsi_high = rsi > 65
            if rsi_high:
                logger.info(f"   ✅ RSI still overbought: {rsi:.1f}")
            
            # 5. Check for SHOOTING STAR / DOJI at top
            is_doji = body < total_range * 0.1  # Body < 10% of range
            shooting_star = upper_wick > body * 3 and is_doji
            if shooting_star:
                logger.info(f"   ✅ Shooting Star/Doji at top!")
            
            # Decision logic based on step number
            signals_count = sum([has_pin_bar, volume_exhaustion, bearish_engulf, rsi_high, shooting_star])
            
            if step_num == 4:
                # Step 4: Need at least 1 signal
                approved = signals_count >= 1
            elif step_num == 5:
                # Step 5: Need at least 2 signals
                approved = signals_count >= 2
            elif step_num >= 6:
                # Step 6+: Need at least 2 signals + RSI high
                approved = signals_count >= 2 and rsi_high
            else:
                approved = True
            
            if approved:
                logger.info(f"   🦅 Step {step_num} APPROVED! ({signals_count} signals)")
            else:
                logger.info(f"   ⏳ Step {step_num} waiting... ({signals_count} signals, need more)")
            
            return approved
            
        except Exception as e:
            logger.debug(f"Eagle-eye check failed for {symbol}: {e}")
            return step_num <= 3  # Only allow early steps on error
    
    def scan_for_new_entries(self) -> list:
        """
        Scan pumped coins for new SHORT entry opportunities
        
        Returns:
            List of symbols to enter
        """
        if not self.martingale.can_open_new_position():
            return []
        
        opportunities = []
        
        # Refresh pumped coins list
        pumped = self.pump_detector.find_pumped_coins()
        
        for coin in pumped[:10]:  # Check top 10 pumped
            symbol = coin['symbol']
            
            # Skip if already have position
            if self.martingale.has_position(symbol):
                continue
            
            try:
                # Get klines for entry check
                klines = self.client.get_klines(symbol, '5m', 50)
                if not klines:
                    continue
                
                import pandas as pd
                columns = ['open_time', 'open', 'high', 'low', 'close', 'volume', 
                          'close_time', 'quote_volume', 'trades', 'taker_buy_volume', 
                          'taker_buy_quote_volume', 'ignore']
                df = pd.DataFrame(klines, columns=columns)
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                
                # Check entry conditions
                entry = self.pump_detector.is_entry_ready(symbol, df)
                
                if entry['ready']:
                    opportunities.append({
                        'symbol': symbol,
                        'pump': coin['pump_percent'],
                        'price': coin['price'],
                        'reason': entry['reason'],
                        'strength': entry['strength']
                    })
                    
                    logger.info(f"🔍 Entry opportunity: {symbol}")
                    logger.info(f"   Pump: +{coin['pump_percent']:.1f}% | {entry['reason']}")
                    
            except Exception as e:
                logger.debug(f"Entry scan failed for {symbol}: {e}")
        
        return opportunities
    
    def log_status(self):
        """Log current position status"""
        status = self.martingale.get_status()
        
        if status['active_positions'] == 0:
            return
        
        logger.info(f"📊 Martingale Status: {status['active_positions']} positions")
        
        for symbol, pos in status['positions'].items():
            try:
                ticker = self.client.get_mark_price(symbol)
                current_price = float(ticker.get('markPrice', 0)) if ticker else 0
                
                # Calculate unrealized P&L
                position = self.martingale.get_position(symbol)
                if position and current_price > 0:
                    upnl = (position.average_entry - current_price) * position.total_quantity
                    upnl_percent = ((position.average_entry - current_price) / position.average_entry) * 100
                    
                    logger.info(f"   {symbol}: Step {pos['step']}/9 | Avg {pos['average_entry']:.6f}")
                    logger.info(f"      Margin: ${pos['total_margin']} | UPnL: ${upnl:.2f} ({upnl_percent:+.2f}%)")
                    
            except Exception as e:
                logger.debug(f"Status log failed for {symbol}: {e}")


if __name__ == "__main__":
    print("Position Watcher loaded successfully!")
