"""
Martingale Manager - Handle step-based counter-trend positions
"""

import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from logger import logger
import config


@dataclass
class MartingalePosition:
    """Track a Martingale position with multiple entries"""
    symbol: str
    side: str  # Always 'SELL' for short
    entries: List[Dict] = field(default_factory=list)
    step: int = 0
    total_quantity: float = 0
    total_margin: float = 0
    average_entry: float = 0
    created_at: datetime = field(default_factory=datetime.now)
    last_step_time: datetime = field(default_factory=datetime.now)
    half_closed: bool = False
    recycle_count: int = 0  # Number of times margin was recycled
    recycled_margin: float = 0  # Total margin freed via recycling
    # Trailing TP fields
    trailing_tp_active: bool = False  # True when in trailing mode
    max_profit_usd: float = 0  # Maximum profit reached (for trailing)


@dataclass
class StopLossRecord:
    """Track a single stop loss event"""
    symbol: str
    timestamp: datetime
    reason: str
    loss_usd: float


class DynamicBlacklist:
    """
    Track stop losses and auto-blacklist tokens with repeated losses.
    
    Rule: If a token has N stop losses within X hours, blacklist it for Y hours.
    """
    def __init__(self):
        self.stop_loss_history: List[StopLossRecord] = []
        self.blacklisted: Dict[str, datetime] = {}  # symbol -> blacklist_until
        
        # Load settings from config
        self.enabled = getattr(config, 'DYNAMIC_BLACKLIST_ENABLED', True)
        self.max_stop_losses = getattr(config, 'DYNAMIC_BLACKLIST_STOP_LOSSES', 2)
        self.window_hours = getattr(config, 'DYNAMIC_BLACKLIST_WINDOW_HOURS', 2)
        self.blacklist_hours = getattr(config, 'DYNAMIC_BLACKLIST_DURATION_HOURS', 6)
        
        logger.info(f"🚫 Dynamic Blacklist: {self.max_stop_losses} SLs in {self.window_hours}h → {self.blacklist_hours}h ban")
    
    def record_stop_loss(self, symbol: str, reason: str, loss_usd: float):
        """Record a stop loss event and check if token should be blacklisted"""
        if not self.enabled:
            return
        
        record = StopLossRecord(
            symbol=symbol,
            timestamp=datetime.now(),
            reason=reason,
            loss_usd=loss_usd
        )
        self.stop_loss_history.append(record)
        
        # Check if we should blacklist this token
        self._check_and_blacklist(symbol)
        
        # Clean old history (older than 24h)
        self._cleanup_old_records()
    
    def _check_and_blacklist(self, symbol: str):
        """Check if token has too many stop losses in window"""
        cutoff = datetime.now() - timedelta(hours=self.window_hours)
        
        recent_losses = [
            r for r in self.stop_loss_history
            if r.symbol == symbol and r.timestamp >= cutoff
        ]
        
        if len(recent_losses) >= self.max_stop_losses:
            blacklist_until = datetime.now() + timedelta(hours=self.blacklist_hours)
            self.blacklisted[symbol] = blacklist_until
            
            total_loss = sum(r.loss_usd for r in recent_losses)
            logger.warning(f"🚫 BLACKLISTED: {symbol} for {self.blacklist_hours}h")
            logger.warning(f"   Reason: {len(recent_losses)} stop losses in {self.window_hours}h")
            logger.warning(f"   Total loss: ${abs(total_loss):.2f}")
    
    def is_blacklisted(self, symbol: str) -> bool:
        """Check if a token is currently blacklisted"""
        if not self.enabled:
            return False
        
        if symbol not in self.blacklisted:
            return False
        
        # Check if blacklist expired
        if datetime.now() >= self.blacklisted[symbol]:
            del self.blacklisted[symbol]
            logger.info(f"✅ {symbol} removed from dynamic blacklist (expired)")
            return False
        
        return True
    
    def get_blacklist_status(self, symbol: str) -> Dict:
        """Get blacklist status for a symbol"""
        if symbol not in self.blacklisted:
            return {'blacklisted': False}
        
        expires = self.blacklisted[symbol]
        remaining = (expires - datetime.now()).total_seconds() / 3600
        
        return {
            'blacklisted': True,
            'expires': expires,
            'remaining_hours': max(0, remaining)
        }
    
    def _cleanup_old_records(self):
        """Remove records older than 24 hours"""
        cutoff = datetime.now() - timedelta(hours=24)
        self.stop_loss_history = [
            r for r in self.stop_loss_history
            if r.timestamp >= cutoff
        ]


class MartingaleManager:
    """
    Manage Martingale-style counter-trend positions
    
    - SHORT ONLY on pumped coins
    - Ultra-light early steps
    - Patient step timing
    - Dynamic half-close
    """
    
    # Load from config - extended to 15 steps for recycling strategy
    # Load from config - extended to 15 steps
    STEPS = getattr(config, 'MARTINGALE_STEPS', [
        3, 3, 5, 5, 7, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100
    ])
    
    STEP_DISTANCES = getattr(config, 'MARTINGALE_STEP_DISTANCES', [
        0, 3, 5, 8, 12, 16, 20, 25, 30, 35, 40, 45, 50, 60, 70
    ])
    
    STEP_WAIT_TIMES = getattr(config, 'MARTINGALE_STEP_WAIT_TIMES', [
        0, 2, 2, 3, 3, 5, 5, 10, 10, 15, 20, 30, 45, 60, 90
    ])
    
    # Margin recycling settings
    RECYCLE_AFTER_STEP = 5  # Start recycling after this step
    MAX_RECYCLES = 10  # Maximum recycling operations per position
    
    # Dynamic position limits based on total margin
    MARGIN_THRESHOLD = 200  # Dollar amount threshold
    MAX_POSITIONS_BELOW_THRESHOLD = 8  # Max positions when margin < $200
    MAX_POSITIONS_ABOVE_THRESHOLD = 4  # Max positions when margin >= $200
    
    def __init__(self, client, executor):
        self.client = client
        self.executor = executor
        self.positions: Dict[str, MartingalePosition] = {}
        self.dynamic_blacklist = DynamicBlacklist()
        
        # Load settings from config if available
        self.max_positions = getattr(config, 'MARTINGALE_MAX_POSITIONS', 3)
        self.emergency_stop_percent = getattr(config, 'MARTINGALE_EMERGENCY_STOP', 20)
        self.half_close_threshold = getattr(config, 'MARTINGALE_HALF_CLOSE_PERCENT', 2)
        
        logger.info("🎰 Martingale Manager initialized")
        logger.info(f"   Steps: {self.STEPS}")
        logger.info(f"   Dynamic limits: {self.MAX_POSITIONS_BELOW_THRESHOLD} pos < ${self.MARGIN_THRESHOLD}, {self.MAX_POSITIONS_ABOVE_THRESHOLD} pos >= ${self.MARGIN_THRESHOLD}")
    
    def recover_positions(self) -> int:
        """
        Recover existing positions from Binance on startup
        
        This allows the bot to continue managing positions after a restart
        """
        try:
            # Get all open positions from Binance
            positions = self.client.get_positions()
            if not positions:
                logger.info("📦 No existing positions to recover")
                return 0
            
            recovered = 0
            for pos in positions:
                symbol = pos.get('symbol', '')
                position_amt = float(pos.get('positionAmt', 0))
                entry_price = float(pos.get('entryPrice', 0))
                unrealized_pnl = float(pos.get('unRealizedProfit', 0))
                
                # Only recover SHORT positions (negative positionAmt)
                if position_amt >= 0 or entry_price <= 0:
                    continue
                
                # Get margin from Binance (prefer initialMargin, fallback to calculation)
                quantity = abs(position_amt)
                margin = float(pos.get('initialMargin', 0)) or float(pos.get('isolatedMargin', 0))
                if margin == 0:
                    notional = quantity * entry_price
                    margin = notional / 10  # Fallback to calculation
                
                # Estimate step based on margin
                step = self._estimate_step_from_margin(margin)
                
                # Create position object
                martingale_pos = MartingalePosition(
                    symbol=symbol,
                    side='SELL',
                    entries=[{
                        'price': entry_price,
                        'quantity': quantity,
                        'margin': margin,
                        'recovered': True
                    }],
                    step=step,
                    total_quantity=quantity,
                    total_margin=margin,
                    average_entry=entry_price
                )
                
                self.positions[symbol] = martingale_pos
                recovered += 1
                
                logger.info(f"♻️ Recovered position: {symbol}")
                logger.info(f"   Entry: {entry_price:.6f} | Qty: {quantity:.4f}")
                logger.info(f"   Estimated Step: {step} | Margin: ${margin:.2f}")
                logger.info(f"   UPnL: ${unrealized_pnl:.2f}")
            
            if recovered > 0:
                logger.info(f"✅ Recovered {recovered} positions from Binance")
            
            return recovered
            
        except Exception as e:
            logger.error(f"Failed to recover positions: {e}")
            return 0
    
    def _estimate_step_from_margin(self, margin: float) -> int:
        """Estimate which step based on total margin used"""
        cumulative = 0
        for i, step_margin in enumerate(self.STEPS):
            cumulative += step_margin
            if margin <= cumulative * 1.2:  # 20% tolerance
                return i + 1
        return len(self.STEPS)  # Max step
    
    def get_total_margin(self) -> float:
        """Get total margin used across all positions"""
        return sum(pos.total_margin for pos in self.positions.values())
    
    def get_dynamic_max_positions(self) -> int:
        """Get max positions based on current total margin"""
        total_margin = self.get_total_margin()
        if total_margin >= self.MARGIN_THRESHOLD:
            return self.MAX_POSITIONS_ABOVE_THRESHOLD
        return self.MAX_POSITIONS_BELOW_THRESHOLD
    
    def can_open_new_position(self) -> bool:
        """Check if we can open a new Martingale position"""
        max_pos = self.get_dynamic_max_positions()
        return len(self.positions) < max_pos
    
    def has_position(self, symbol: str) -> bool:
        """Check if we have an active Martingale position"""
        return symbol in self.positions
    
    def get_position(self, symbol: str) -> Optional[MartingalePosition]:
        """Get Martingale position for symbol"""
        return self.positions.get(symbol)
    
    def open_position(self, symbol: str, current_price: float) -> bool:
        """
        Open a new Martingale SHORT position (Step 1)
        """
        if not self.can_open_new_position():
            logger.warning(f"Max Martingale positions reached ({self.max_positions})")
            return False
        
        if self.has_position(symbol):
            logger.warning(f"Already have Martingale position for {symbol}")
            return False
        
        # Check dynamic blacklist
        if self.dynamic_blacklist.is_blacklisted(symbol):
            status = self.dynamic_blacklist.get_blacklist_status(symbol)
            logger.info(f"⏭️ Skipping {symbol} - Dynamic blacklist ({status['remaining_hours']:.1f}h remaining)")
            return False
        
        margin = self.STEPS[0]  # First step margin
        
        try:
            # Calculate quantity
            quantity = self._calculate_quantity(symbol, margin, current_price)
            
            if quantity <= 0:
                logger.error(f"Invalid quantity for {symbol}")
                return False
            
            # Setup symbol and execute SHORT entry
            self.executor.setup_symbol(symbol)
            result = self.client.place_market_order(
                symbol=symbol,
                side='SELL',
                quantity=quantity
            )
            
            if result:
                # Create Martingale position
                position = MartingalePosition(
                    symbol=symbol,
                    side='SELL',
                    entries=[{
                        'step': 1,
                        'price': current_price,
                        'quantity': quantity,
                        'margin': margin,
                        'time': datetime.now()
                    }],
                    step=1,
                    total_quantity=quantity,
                    total_margin=margin,
                    average_entry=current_price
                )
                
                self.positions[symbol] = position
                
                logger.info(f"🎰 Martingale Step 1: {symbol} SHORT")
                logger.info(f"   Entry: {current_price:.6f} | Margin: ${margin}")
                
                return True
            
        except Exception as e:
            logger.error(f"Failed to open Martingale position: {e}")
        
        return False
    
    def should_add_step(self, symbol: str, current_price: float) -> Dict:
        """
        Check if we should add another step to position
        
        Conditions:
        - Price moved up enough (distance requirement)
        - Enough time passed (patience requirement)
        - Not at max steps
        
        Returns:
            Dict with should_add, reason, step_num
        """
        position = self.get_position(symbol)
        if not position:
            return {'should_add': False, 'reason': 'No position'}
        
        current_step = position.step
        max_steps = len(self.STEPS)
        
        if current_step >= max_steps:
            return {'should_add': False, 'reason': 'Max steps reached'}
        
        next_step = current_step + 1
        
        # Calculate current unrealized loss in USD
        current_loss = (current_price - position.average_entry) * position.total_quantity
        margin_loss_percent = (current_loss / position.total_margin) * 100 if position.total_margin > 0 else 0
        
        # For steps 1-3: Use margin-loss based entry with progressive thresholds
        # Step 1 → 2: 70% loss
        # Step 2 → 3: 80% loss
        # Step 3 → 4: 90% loss
        # Step 4+: Eagle-eye mode (distance-based with confirmation)
        if current_step <= 3:
            # Progressive loss thresholds
            if current_step == 1:
                required_loss_percent = 70
            elif current_step == 2:
                required_loss_percent = 80
            else:  # step 3
                required_loss_percent = 90
            
            if margin_loss_percent < required_loss_percent:
                return {
                    'should_add': False,
                    'reason': f'Margin loss {margin_loss_percent:.0f}% < {required_loss_percent}% required',
                    'margin_loss': margin_loss_percent,
                    'current_loss': current_loss
                }
            
            # Loss threshold reached - ready for next step
            return {
                'should_add': True,
                'reason': f'Margin loss {margin_loss_percent:.0f}% >= {required_loss_percent}% - Ready!',
                'step_num': next_step,
                'margin': self.STEPS[next_step - 1],
                'margin_loss': margin_loss_percent,
                'current_loss': current_loss
            }
        
        # For steps 5+: Use distance-based entry (original logic)
        distance_percent = ((current_price - position.average_entry) / position.average_entry) * 100
        required_distance = self.STEP_DISTANCES[next_step - 1] if next_step <= len(self.STEP_DISTANCES) else 50
        
        # Time since last step
        time_since_last = (datetime.now() - position.last_step_time).total_seconds() / 60
        required_wait = self.STEP_WAIT_TIMES[next_step - 1] if next_step <= len(self.STEP_WAIT_TIMES) else 0
        
        # Check distance
        if distance_percent < required_distance:
            return {
                'should_add': False,
                'reason': f'Distance {distance_percent:.1f}% < {required_distance}% required',
                'distance': distance_percent,
                'time_waiting': time_since_last
            }
        
        # Check time (can be overridden if distance is very high)
        if time_since_last < required_wait:
            # Allow override if distance is 1.5x required
            if distance_percent < required_distance * 1.5:
                return {
                    'should_add': False,
                    'reason': f'Wait time {time_since_last:.0f}min < {required_wait}min required',
                    'distance': distance_percent,
                    'time_waiting': time_since_last
                }
        
        return {
            'should_add': True,
            'reason': f'Distance {distance_percent:.1f}% + Wait {time_since_last:.0f}min',
            'step_num': next_step,
            'margin': self.STEPS[next_step - 1],
            'distance': distance_percent,
            'time_waiting': time_since_last
        }
    
    def add_step(self, symbol: str, current_price: float) -> bool:
        """
        Add another step to the Martingale position
        """
        position = self.get_position(symbol)
        if not position:
            return False
        
        next_step = position.step + 1
        if next_step > len(self.STEPS):
            return False
        
        margin = self.STEPS[next_step - 1]
        
        try:
            quantity = self._calculate_quantity(symbol, margin, current_price)
            
            if quantity <= 0:
                return False
            
            # Execute additional SHORT
            result = self.client.place_market_order(
                symbol=symbol,
                side='SELL',
                quantity=quantity
            )
            
            if result:
                # Update position
                position.entries.append({
                    'step': next_step,
                    'price': current_price,
                    'quantity': quantity,
                    'margin': margin,
                    'time': datetime.now()
                })
                
                position.step = next_step
                position.total_quantity += quantity
                position.total_margin += margin
                position.last_step_time = datetime.now()
                
                # Recalculate average entry
                position.average_entry = self._calculate_average(position)
                
                logger.info(f"🎰 Martingale Step {next_step}: {symbol}")
                logger.info(f"   Price: {current_price:.6f} | Margin: ${margin}")
                logger.info(f"   New Avg: {position.average_entry:.6f} | Total Margin: ${position.total_margin}")
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to add Martingale step: {e}")
        
        return False
    
    def should_close_half(self, symbol: str, current_price: float) -> Dict:
        """
        Check if we should close half the position
        
        Condition: Price returned within threshold of average after step 3+
        """
        position = self.get_position(symbol)
        if not position:
            return {'should_close': False}
        
        # Only half-close Step 3+. Step 1-2 too small.
        if position.step < 3:
            return {'should_close': False, 'reason': 'Step < 3'}
        
        if position.half_closed:
            return {'should_close': False, 'reason': 'Already half-closed'}
        
        # For SHORT: profit when price drops (current < average)
        # Negative distance = profit for SHORT
        distance_to_avg = ((current_price - position.average_entry) / position.average_entry) * 100
        
        # Calculate actual P&L in USD
        pnl_usd = (position.average_entry - current_price) * position.total_quantity
        
        # Dynamic half-close threshold: 50% of TP target
        # This locks in profit while letting the rest ride
        step = position.step
        if step == 3:
            min_profit = 3.0   # TP is $6, half-close at $3
        elif step == 4:
            min_profit = 4.0   # TP is $8, half-close at $4
        elif step == 5:
            min_profit = 5.0   # TP is $10, half-close at $5
        elif step <= 7:
            min_profit = 6.0   # TP is $12, half-close at $6
        else:  # step 8+
            min_profit = 10.0  # TP is $20, half-close at $10
        
        # Half-close when profit reaches threshold
        if pnl_usd >= min_profit:
            return {
                'should_close': True,
                'reason': f'Step {step} half-close at ${pnl_usd:.2f} (target ${min_profit})',
                'pnl_usd': pnl_usd
            }
        
        return {'should_close': False, 'reason': f'Profit ${pnl_usd:.2f} < ${min_profit}', 'pnl_usd': pnl_usd}
    
    def close_half(self, symbol: str, current_price: float) -> bool:
        """Close half of the Martingale position"""
        position = self.get_position(symbol)
        if not position:
            return False
        
        half_quantity = position.total_quantity / 2
        
        try:
            # Close half (BUY to close SHORT)
            result = self.client.place_market_order(
                symbol=symbol,
                side='BUY',
                quantity=self.client.round_quantity(symbol, half_quantity)
            )
            
            if result:
                position.total_quantity = half_quantity
                position.half_closed = True
                
                # Calculate P&L on closed portion
                pnl = (position.average_entry - current_price) * half_quantity
                
                logger.info(f"🎰 Half-Close: {symbol}")
                logger.info(f"   Closed: {half_quantity:.4f} @ {current_price:.6f}")
                logger.info(f"   P&L: ${pnl:.2f}")
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to close half: {e}")
        
        return False
    
    def should_auto_close_early(self, symbol: str, current_price: float) -> Dict:
        """
        Check if we should auto-close an early step position to free margin
        
        Conditions:
        - Total margin >= $100 threshold
        - Position is at step 1-3
        - Position has small profit (>= $0.50) OR small loss (<= $1)
        - We have more positions than MAX_POSITIONS_ABOVE_THRESHOLD
        """
        position = self.get_position(symbol)
        if not position:
            return {'should_close': False}
        
        total_margin = self.get_total_margin()
        
        # Only trigger when margin is at threshold
        if total_margin < self.MARGIN_THRESHOLD:
            return {'should_close': False, 'reason': f'Margin ${total_margin:.0f} < ${self.MARGIN_THRESHOLD}'}
        
        # Only close early step positions (1-3)
        if position.step > 3:
            return {'should_close': False, 'reason': f'Step {position.step} > 3'}
        
        # Only trigger when we have too many positions
        if len(self.positions) <= self.MAX_POSITIONS_ABOVE_THRESHOLD:
            return {'should_close': False, 'reason': f'Only {len(self.positions)} positions'}
        
        # Calculate P&L
        pnl_usd = (position.average_entry - current_price) * position.total_quantity
        
        # Close if small profit (>= $0.50) or small loss (<= $1)
        if pnl_usd >= 0.5:
            return {
                'should_close': True,
                'reason': f'Small profit ${pnl_usd:.2f} - freeing margin',
                'pnl_usd': pnl_usd
            }
        
        if pnl_usd >= -1.0:  # Small loss up to $1
            return {
                'should_close': True,
                'reason': f'Small loss ${pnl_usd:.2f} - freeing margin',
                'pnl_usd': pnl_usd
            }
        
        return {'should_close': False, 'reason': f'P&L ${pnl_usd:.2f} not in range', 'pnl_usd': pnl_usd}
    
    def should_recycle_margin(self, symbol: str, current_price: float) -> Dict:
        """
        Check if we should recycle margin to allow more steps
        
        Conditions:
        - Step >= RECYCLE_AFTER_STEP (5)
        - Price has returned closer to average (within 1%)
        - Haven't exceeded MAX_RECYCLES
        """
        # DISABLED: Recycle was closing positions too early before TP
        # Let positions reach their full TP targets
        return {'should_recycle': False, 'reason': 'Recycle disabled - wait for TP'}
        
        position = self.get_position(symbol)
        if not position:
            return {'should_recycle': False}
        
        if position.step < self.RECYCLE_AFTER_STEP:
            return {'should_recycle': False, 'reason': f'Step {position.step} < {self.RECYCLE_AFTER_STEP}'}
        
        if position.recycle_count >= self.MAX_RECYCLES:
            return {'should_recycle': False, 'reason': f'Max recycles reached ({self.MAX_RECYCLES})'}
        
        # For SHORT: check if price has come down closer to average
        distance_to_avg = ((current_price - position.average_entry) / position.average_entry) * 100
        
        # Calculate actual P&L in USD
        pnl_usd = (position.average_entry - current_price) * position.total_quantity
        
        # Recycle when price returns within 1% of average AND in profit
        if distance_to_avg <= 1 and distance_to_avg > -3:
            if pnl_usd >= 1.0:  # Must have $1+ profit to recycle!
                return {
                    'should_recycle': True,
                    'reason': f'Price near average ({distance_to_avg:.1f}%) + Profit ${pnl_usd:.2f}',
                    'distance': distance_to_avg,
                    'pnl_usd': pnl_usd
                }
        
        return {'should_recycle': False, 'reason': f'Distance {distance_to_avg:.1f}%'}
    
    def recycle_margin(self, symbol: str, current_price: float) -> bool:
        """
        Recycle margin by closing half position to free up for more steps
        
        This allows extending from 9 steps to 15+ steps
        """
        position = self.get_position(symbol)
        if not position:
            return False
        
        if position.total_quantity <= 0:
            return False
        
        # Close 40% of position (not full half, to keep some exposure)
        recycle_quantity = position.total_quantity * 0.4
        
        try:
            result = self.client.place_market_order(
                symbol=symbol,
                side='BUY',  # Close SHORT
                quantity=self.client.round_quantity(symbol, recycle_quantity)
            )
            
            if result:
                # Calculate P&L on recycled portion
                pnl = (position.average_entry - current_price) * recycle_quantity
                
                # Calculate freed margin
                freed_margin = position.total_margin * 0.4
                
                # Update position
                position.total_quantity -= recycle_quantity
                position.total_margin -= freed_margin
                position.recycle_count += 1
                position.recycled_margin += freed_margin
                
                logger.info(f"♻️ Margin Recycled: {symbol}")
                logger.info(f"   Closed: {recycle_quantity:.4f} @ {current_price:.6f}")
                logger.info(f"   P&L: ${pnl:.2f} | Freed: ${freed_margin:.2f}")
                logger.info(f"   Recycle #{position.recycle_count} | Total freed: ${position.recycled_margin:.2f}")
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to recycle margin: {e}")
        
        return False
    
    def should_emergency_close(self, symbol: str, current_price: float) -> Dict:
        """
        Check if we should emergency close position
        
        Condition: Drawdown exceeds threshold
        """
        position = self.get_position(symbol)
        if not position:
            return {'should_close': False}
        
        # For SHORT: loss when price goes up
        drawdown_percent = ((current_price - position.average_entry) / position.average_entry) * 100
        
        # Calculate USD loss
        usd_loss = (position.average_entry - current_price) * position.total_quantity
        hard_stop_usd = getattr(config, 'MARTINGALE_HARD_STOP_USD', 55)
        
        # 1. USD Hard Stop
        # Note: usd_loss is negative when losing
        if usd_loss <= -hard_stop_usd:
             return {
                'should_close': True,
                'reason': f'🚨 HARD STOP: Loss ${abs(usd_loss):.2f} > ${hard_stop_usd}',
                'drawdown': drawdown_percent,
                'pnl': usd_loss
            }
        
        # 2. Percentage Drawdown Stop
        if drawdown_percent >= self.emergency_stop_percent:
            return {
                'should_close': True,
                'reason': f'Emergency! Drawdown {drawdown_percent:.1f}%',
                'drawdown': drawdown_percent
            }
        
        return {'should_close': False, 'drawdown': drawdown_percent}
    
    def close_position(self, symbol: str, current_price: float, reason: str = "") -> bool:
        """Close entire Martingale position"""
        position = self.get_position(symbol)
        if not position:
            return False
        
        try:
            # Close all (BUY to close SHORT)
            result = self.client.place_market_order(
                symbol=symbol,
                side='BUY',
                quantity=self.client.round_quantity(symbol, position.total_quantity)
            )
            
            if result:
                # Calculate final P&L
                pnl = (position.average_entry - current_price) * position.total_quantity
                pnl_percent = ((position.average_entry - current_price) / position.average_entry) * 100
                
                logger.info(f"🎰 Position Closed: {symbol}")
                logger.info(f"   Reason: {reason}")
                logger.info(f"   Steps: {position.step} | Margin: ${position.total_margin}")
                logger.info(f"   P&L: ${pnl:.2f} ({pnl_percent:.2f}%)")
                
                # Record stop loss if it was a loss closure
                if pnl < 0 and ("stop" in reason.lower() or "emergency" in reason.lower() or "hard" in reason.lower()):
                    self.dynamic_blacklist.record_stop_loss(symbol, reason, pnl)
                
                # Remove position
                del self.positions[symbol]
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to close position: {e}")
        
        return False
    
    def _calculate_quantity(self, symbol: str, margin: float, price: float) -> float:
        """Calculate position quantity from margin"""
        leverage = getattr(config, 'LEVERAGE', 5)
        position_value = margin * leverage
        quantity = position_value / price
        return self.client.round_quantity(symbol, quantity)
    
    def _calculate_average(self, position: MartingalePosition) -> float:
        """Calculate weighted average entry price"""
        if not position.entries:
            return 0
        
        total_value = sum(e['price'] * e['quantity'] for e in position.entries)
        total_qty = sum(e['quantity'] for e in position.entries)
        
        return total_value / total_qty if total_qty > 0 else 0
    
    def sync_positions(self) -> Dict:
        """
        Sync internal position tracking with Binance's actual positions
        
        This fixes quantity/margin mismatches that can occur from:
        - Half-closes not updating correctly
        - Partial fills
        - Manual interventions
        - Bot restarts
        
        Returns:
            Dict with sync results (updated, removed, added)
        """
        results = {'updated': [], 'removed': [], 'added': [], 'errors': []}
        
        try:
            # Get all open positions from Binance
            binance_positions = self.client.get_positions()
            binance_symbols = set()
            
            for pos in binance_positions:
                symbol = pos.get('symbol', '')
                position_amt = float(pos.get('positionAmt', 0))
                entry_price = float(pos.get('entryPrice', 0))
                
                # Only process SHORT positions (negative positionAmt)
                if position_amt >= 0 or entry_price <= 0:
                    continue
                
                binance_symbols.add(symbol)
                quantity = abs(position_amt)
                
                # Use Binance's actual margin (prefer initialMargin, fallback to isolatedMargin)
                margin = float(pos.get('initialMargin', 0)) or float(pos.get('isolatedMargin', 0))
                if margin == 0:
                    # Fallback: calculate from notional
                    notional = quantity * entry_price
                    margin = notional / 10
                
                if symbol in self.positions:
                    # Update existing position
                    local_pos = self.positions[symbol]
                    old_qty = local_pos.total_quantity
                    old_margin = local_pos.total_margin
                    
                    # Check for significant differences
                    qty_diff = abs(local_pos.total_quantity - quantity)
                    if qty_diff > 0.001 * quantity:  # More than 0.1% difference
                        local_pos.total_quantity = quantity
                        local_pos.total_margin = margin
                        local_pos.average_entry = entry_price
                        results['updated'].append({
                            'symbol': symbol,
                            'old_qty': old_qty,
                            'new_qty': quantity,
                            'old_margin': old_margin,
                            'new_margin': margin
                        })
                        logger.info(f"🔄 Synced {symbol}: Qty {old_qty:.4f}→{quantity:.4f}, Margin ${old_margin:.2f}→${margin:.2f}")
                else:
                    # Position exists on Binance but not tracked locally - add it
                    step = self._estimate_step_from_margin(margin)
                    new_pos = MartingalePosition(
                        symbol=symbol,
                        side='SELL',
                        entries=[{
                            'price': entry_price,
                            'quantity': quantity,
                            'margin': margin,
                            'synced': True
                        }],
                        step=step,
                        total_quantity=quantity,
                        total_margin=margin,
                        average_entry=entry_price
                    )
                    self.positions[symbol] = new_pos
                    results['added'].append(symbol)
                    logger.info(f"➕ Added untracked position: {symbol} (Step {step}, ${margin:.2f})")
            
            # Check for positions we track but no longer exist on Binance
            tracked_symbols = list(self.positions.keys())
            for symbol in tracked_symbols:
                if symbol not in binance_symbols:
                    del self.positions[symbol]
                    results['removed'].append(symbol)
                    logger.info(f"➖ Removed closed position: {symbol}")
            
            # Log summary
            if results['updated'] or results['removed'] or results['added']:
                logger.info(f"🔄 Sync complete: {len(results['updated'])} updated, {len(results['removed'])} removed, {len(results['added'])} added")
            
        except Exception as e:
            logger.error(f"Position sync failed: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def get_status(self) -> Dict:
        """Get status of all Martingale positions"""
        status = {
            'active_positions': len(self.positions),
            'positions': {}
        }
        
        for symbol, pos in self.positions.items():
            status['positions'][symbol] = {
                'step': pos.step,
                'total_margin': pos.total_margin,
                'average_entry': pos.average_entry,
                'half_closed': pos.half_closed,
                'entries': len(pos.entries)
            }
        
        return status


if __name__ == "__main__":
    print("Martingale Manager loaded successfully!")
    print(f"Steps: {MartingaleManager.STEPS}")
    print(f"Total max margin: ${sum(MartingaleManager.STEPS)}")
