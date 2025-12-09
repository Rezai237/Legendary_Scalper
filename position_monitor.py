"""
Position Monitor Module
Monitors open positions and updates trailing stop losses
"""

import config
from logger import logger
from typing import Dict, List, Optional


class PositionMonitor:
    """Monitors positions and manages trailing stops"""
    
    def __init__(self, client):
        self.client = client
        # Track entry prices and highest prices for trailing
        self.position_data = {}  # {symbol: {'entry_price': x, 'highest': x, 'lowest': x, 'side': 'BUY/SELL'}}
    
    def update_position_tracking(self, positions: List[Dict]):
        """Update tracked positions with current market data"""
        current_symbols = set()
        
        for pos in positions:
            symbol = pos['symbol']
            position_amt = float(pos.get('positionAmt', 0))
            
            if position_amt == 0:
                continue
                
            current_symbols.add(symbol)
            entry_price = float(pos.get('entryPrice', 0))
            mark_price = float(pos.get('markPrice', 0))
            side = 'BUY' if position_amt > 0 else 'SELL'
            
            if symbol not in self.position_data:
                # New position
                self.position_data[symbol] = {
                    'entry_price': entry_price,
                    'highest': mark_price,
                    'lowest': mark_price,
                    'side': side,
                    'quantity': abs(position_amt),
                    'trailing_active': False
                }
                logger.debug(f"Tracking new position: {symbol} {side}")
            else:
                # Update existing position
                data = self.position_data[symbol]
                data['highest'] = max(data['highest'], mark_price)
                data['lowest'] = min(data['lowest'], mark_price)
                data['quantity'] = abs(position_amt)
        
        # Remove closed positions from tracking
        closed = set(self.position_data.keys()) - current_symbols
        for symbol in closed:
            del self.position_data[symbol]
            logger.debug(f"Stopped tracking closed position: {symbol}")
    
    def calculate_profit_percent(self, symbol: str, current_price: float) -> float:
        """Calculate current profit percentage for a position"""
        if symbol not in self.position_data:
            return 0.0
        
        data = self.position_data[symbol]
        entry_price = data['entry_price']
        
        if entry_price == 0:
            return 0.0
        
        if data['side'] == 'BUY':
            return ((current_price - entry_price) / entry_price) * 100
        else:  # SELL
            return ((entry_price - current_price) / entry_price) * 100
    
    def calculate_breakeven_stop(self, symbol: str, current_price: float) -> Optional[float]:
        """Calculate break-even stop price (move SL to entry)"""
        if not getattr(config, 'BREAKEVEN_ENABLED', False):
            return None
        
        if symbol not in self.position_data:
            return None
        
        data = self.position_data[symbol]
        
        # Already moved to break-even
        if data.get('breakeven_set', False):
            return None
        
        profit_pct = self.calculate_profit_percent(symbol, current_price)
        activation = getattr(config, 'BREAKEVEN_ACTIVATION', 0.5)
        
        # Check if profit threshold is met
        if profit_pct >= activation:
            entry_price = data['entry_price']
            # Add small buffer to cover fees
            if data['side'] == 'BUY':
                new_stop = entry_price * 1.001  # 0.1% above entry
            else:
                new_stop = entry_price * 0.999  # 0.1% below entry
            
            new_stop = self.client.round_price(symbol, new_stop)
            return new_stop
        
        return None
    
    def check_partial_take_profit(self, symbol: str, current_price: float) -> bool:
        """Check and execute partial take profit (close 50% of position)"""
        if not getattr(config, 'PARTIAL_TP_ENABLED', False):
            return False
        
        if symbol not in self.position_data:
            return False
        
        data = self.position_data[symbol]
        
        # Already took partial profit
        if data.get('partial_tp_done', False):
            return False
        
        profit_pct = self.calculate_profit_percent(symbol, current_price)
        activation = getattr(config, 'PARTIAL_TP_ACTIVATION', 1.0)
        
        if profit_pct >= activation:
            try:
                # Calculate partial quantity (50%)
                partial_pct = getattr(config, 'PARTIAL_TP_PERCENT', 50) / 100
                partial_qty = self.client.round_quantity(symbol, data['quantity'] * partial_pct)
                
                if partial_qty > 0:
                    # Close partial position
                    close_side = 'SELL' if data['side'] == 'BUY' else 'BUY'
                    self.client.place_market_order(symbol, close_side, partial_qty)
                    
                    # Update tracking
                    data['partial_tp_done'] = True
                    data['quantity'] -= partial_qty
                    
                    logger.info(f"💰 Partial TP: Closed {partial_pct*100}% of {symbol} at {profit_pct:.2f}% profit")
                    return True
            except Exception as e:
                logger.debug(f"Partial TP failed for {symbol}: {e}")
        
        return False
    
    def calculate_new_trailing_stop(self, symbol: str, current_price: float) -> Optional[float]:
        """Calculate new trailing stop price if needed"""
        if not config.TRAILING_STOP_ENABLED:
            return None
        
        if symbol not in self.position_data:
            return None
        
        data = self.position_data[symbol]
        profit_pct = self.calculate_profit_percent(symbol, current_price)
        
        # Check if profit threshold is met for trailing activation
        if profit_pct < config.TRAILING_STOP_ACTIVATION:
            return None
        
        # Mark trailing as active
        if not data['trailing_active']:
            data['trailing_active'] = True
            logger.info(f"📈 Trailing activated for {symbol} at {profit_pct:.2f}% profit")
        
        # Calculate new stop price
        callback_pct = config.TRAILING_STOP_CALLBACK / 100
        
        if data['side'] == 'BUY':
            # For long, trail below highest price
            new_stop = data['highest'] * (1 - callback_pct)
            # Round to symbol precision
            new_stop = self.client.round_price(symbol, new_stop)
        else:  # SELL
            # For short, trail above lowest price
            new_stop = data['lowest'] * (1 + callback_pct)
            new_stop = self.client.round_price(symbol, new_stop)
        
        return new_stop
    
    def update_trailing_stops(self, positions: List[Dict]) -> int:
        """
        Update trailing stops for all positions
        
        Returns:
            Number of stops updated
        """
        # Update tracking data
        self.update_position_tracking(positions)
        
        updated_count = 0
        
        for pos in positions:
            symbol = pos['symbol']
            position_amt = float(pos.get('positionAmt', 0))
            
            if position_amt == 0 or symbol not in self.position_data:
                continue
            
            current_price = float(pos.get('markPrice', 0))
            
            # First check for break-even
            new_stop = self.calculate_breakeven_stop(symbol, current_price)
            is_breakeven = new_stop is not None
            
            # If no break-even, check for trailing
            if new_stop is None and config.TRAILING_STOP_ENABLED:
                new_stop = self.calculate_new_trailing_stop(symbol, current_price)
            
            if new_stop is None:
                continue
            
            # Get current stop orders
            try:
                open_orders = self.client.get_open_orders(symbol)
                stop_orders = [o for o in open_orders if o.get('type') == 'STOP_MARKET']
                
                if not stop_orders:
                    continue
                
                current_stop = float(stop_orders[0].get('stopPrice', 0))
                data = self.position_data[symbol]
                
                # Only update if new stop is better
                should_update = False
                if data['side'] == 'BUY' and new_stop > current_stop:
                    should_update = True
                elif data['side'] == 'SELL' and new_stop < current_stop:
                    should_update = True
                
                if should_update:
                    # Cancel old stop and place new one
                    quantity = data['quantity']
                    stop_side = 'SELL' if data['side'] == 'BUY' else 'BUY'
                    
                    # Cancel existing stop orders
                    self.client.cancel_all_orders(symbol)
                    
                    # Place new stop
                    self.client.place_stop_loss(
                        symbol=symbol,
                        side=stop_side,
                        quantity=quantity,
                        stop_price=new_stop
                    )
                    
                    if is_breakeven:
                        data['breakeven_set'] = True
                        logger.info(f"🛡️ Break-even SL set: {symbol} → {new_stop:.4f}")
                    else:
                        logger.info(f"🔄 Trailing SL updated: {symbol} {current_stop:.4f} → {new_stop:.4f}")
                    updated_count += 1
                    
            except Exception as e:
                logger.debug(f"Error updating trailing stop for {symbol}: {e}")
        
        return updated_count
    
    def get_tracking_info(self) -> Dict:
        """Get current tracking information"""
        return {
            'tracked_positions': len(self.position_data),
            'trailing_active': sum(1 for d in self.position_data.values() if d.get('trailing_active')),
            'positions': self.position_data.copy()
        }


# Test when run directly
if __name__ == "__main__":
    print("Position Monitor Module")
    print("This module monitors positions and manages trailing stops.")
