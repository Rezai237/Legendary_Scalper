"""
Risk Manager Module
Handles position sizing, stop-loss, and take-profit calculations
"""

from typing import Dict, Tuple, Optional
import config
from logger import logger


class RiskManager:
    """Manages trading risk and position sizing"""
    
    def __init__(self, client):
        self.client = client
        self._symbol_info_cache = {}
    
    def get_capital(self) -> float:
        """Get trading capital (fixed or from balance)"""
        if config.USE_FIXED_CAPITAL:
            return config.TOTAL_CAPITAL_USDT
        else:
            return self.client.get_usdt_balance()
    
    def get_symbol_info(self, symbol: str) -> Dict:
        """Get and cache symbol info"""
        if symbol not in self._symbol_info_cache:
            info = self.client.get_symbol_info(symbol)
            if info:
                self._symbol_info_cache[symbol] = info
        return self._symbol_info_cache.get(symbol, {})
    
    def calculate_position_size(self, symbol: str, entry_price: float, 
                                 stop_loss_price: float) -> float:
        """
        Calculate position size based on Initial Margin approach
        
        With 1000 USDT capital and 10x leverage:
        - Initial Margin per trade = 100 USDT
        - Position Value = 100 * 10 = 1000 USDT
        - Quantity = 1000 / entry_price
        
        Args:
            symbol: Trading pair
            entry_price: Entry price
            stop_loss_price: Stop loss price
        
        Returns:
            Position size in base asset
        """
        # Get trading capital
        capital = self.get_capital()
        
        # Calculate Initial Margin for this trade
        initial_margin = config.INITIAL_MARGIN_PER_TRADE
        
        # Cap at max position size
        max_margin = capital * (config.MAX_POSITION_SIZE_PERCENT / 100)
        initial_margin = min(initial_margin, max_margin)
        
        # Calculate position value with leverage
        position_value = initial_margin * config.LEVERAGE
        
        # Convert to quantity
        quantity = position_value / entry_price
        
        # Round to symbol precision
        quantity = self.client.round_quantity(symbol, quantity)
        
        return quantity
    
    def calculate_stop_loss(self, entry_price: float, atr: float, 
                            side: str) -> float:
        """
        Calculate stop loss price based on ATR
        
        Args:
            entry_price: Entry price
            atr: Average True Range value
            side: BUY or SELL
        
        Returns:
            Stop loss price
        """
        stop_distance = atr * config.STOP_LOSS_ATR_MULTIPLIER
        
        # Ensure minimum distance (0.5%) to prevent immediate trigger
        min_distance = entry_price * 0.005
        stop_distance = max(stop_distance, min_distance)
        
        if side == "BUY":
            stop_loss = entry_price - stop_distance
        else:  # SELL
            stop_loss = entry_price + stop_distance
        
        return stop_loss
    
    def calculate_take_profit(self, entry_price: float, stop_loss: float,
                              side: str) -> float:
        """
        Calculate take profit price based on risk/reward ratio
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            side: BUY or SELL
        
        Returns:
            Take profit price
        """
        risk = abs(entry_price - stop_loss)
        reward = risk * config.TAKE_PROFIT_RR_RATIO
        
        if side == "BUY":
            take_profit = entry_price + reward
        else:  # SELL
            take_profit = entry_price - reward
        
        return take_profit
    
    def calculate_smart_stop_loss(self, entry_price: float, atr: float, 
                                   side: str, sr_levels: dict) -> float:
        """
        Calculate smart stop loss using Support/Resistance levels
        Places SL just below support (for BUY) or above resistance (for SELL)
        Falls back to ATR-based SL if no levels found
        
        Args:
            entry_price: Entry price
            atr: ATR value
            side: BUY or SELL
            sr_levels: Support/Resistance levels dict
        
        Returns:
            Smart stop loss price
        """
        atr_sl = self.calculate_stop_loss(entry_price, atr, side)
        
        if not sr_levels:
            return atr_sl
        
        if side == "BUY":
            nearest_support = sr_levels.get('nearest_support')
            if nearest_support:
                # Place SL just below support (0.3% buffer)
                smart_sl = nearest_support * 0.997
                # Use smart SL if it's better than ATR SL (higher = tighter)
                if smart_sl > atr_sl and smart_sl < entry_price * 0.99:
                    return smart_sl
        else:  # SELL
            nearest_resistance = sr_levels.get('nearest_resistance')
            if nearest_resistance:
                # Place SL just above resistance (0.3% buffer)
                smart_sl = nearest_resistance * 1.003
                # Use smart SL if it's better than ATR SL (lower = tighter)
                if smart_sl < atr_sl and smart_sl > entry_price * 1.01:
                    return smart_sl
        
        return atr_sl
    
    def calculate_smart_take_profit(self, entry_price: float, stop_loss: float,
                                     side: str, sr_levels: dict) -> float:
        """
        Calculate smart take profit using Support/Resistance levels
        Places TP at next resistance (for BUY) or support (for SELL)
        Falls back to R:R based TP if no levels found
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            side: BUY or SELL
            sr_levels: Support/Resistance levels dict
        
        Returns:
            Smart take profit price
        """
        rr_tp = self.calculate_take_profit(entry_price, stop_loss, side)
        
        if not sr_levels:
            return rr_tp
        
        if side == "BUY":
            nearest_resistance = sr_levels.get('nearest_resistance')
            if nearest_resistance:
                # Place TP just below resistance (0.2% buffer)
                smart_tp = nearest_resistance * 0.998
                # Only use if gives reasonable R:R (at least 1.5:1)
                risk = entry_price - stop_loss
                reward = smart_tp - entry_price
                if reward >= risk * 1.5:
                    return smart_tp
        else:  # SELL
            nearest_support = sr_levels.get('nearest_support')
            if nearest_support:
                # Place TP just above support (0.2% buffer)
                smart_tp = nearest_support * 1.002
                # Only use if gives reasonable R:R (at least 1.5:1)
                risk = stop_loss - entry_price
                reward = entry_price - smart_tp
                if reward >= risk * 1.5:
                    return smart_tp
        
        return rr_tp
    
    def calculate_trade_params(self, symbol: str, side: str, 
                                entry_price: float, atr: float,
                                sr_levels: dict = None) -> Dict:
        """
        Calculate all trade parameters using Initial Margin approach
        
        With 1000 USDT capital and 10x leverage:
        - Initial Margin = 100 USDT per trade
        - Position Value = 100 * 10 = 1000 USDT
        
        Args:
            symbol: Trading pair
            side: BUY or SELL
            entry_price: Entry price
            atr: ATR value
            sr_levels: Optional Support/Resistance levels for smart SL/TP
        
        Returns:
            Dictionary with quantity, stop_loss, take_profit
        """
        # Calculate stop loss (smart if S/R available)
        if sr_levels:
            stop_loss = self.calculate_smart_stop_loss(entry_price, atr, side, sr_levels)
        else:
            stop_loss = self.calculate_stop_loss(entry_price, atr, side)
        stop_loss = self.client.round_price(symbol, stop_loss)
        
        # Calculate take profit (smart if S/R available)
        if sr_levels:
            take_profit = self.calculate_smart_take_profit(entry_price, stop_loss, side, sr_levels)
        else:
            take_profit = self.calculate_take_profit(entry_price, stop_loss, side)
        take_profit = self.client.round_price(symbol, take_profit)
        
        # Calculate position size (now uses fixed capital internally)
        quantity = self.calculate_position_size(symbol, entry_price, stop_loss)
        
        # Calculate expected profit/loss
        risk_amount = abs(entry_price - stop_loss) * quantity
        reward_amount = abs(take_profit - entry_price) * quantity
        
        # Calculate Initial Margin for display
        initial_margin = (quantity * entry_price) / config.LEVERAGE
        
        return {
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'quantity': quantity,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_usdt': risk_amount,
            'reward_usdt': reward_amount,
            'initial_margin': initial_margin,
            'risk_reward_ratio': config.TAKE_PROFIT_RR_RATIO,
            'smart_sl': sr_levels is not None
        }
    
    def can_open_position(self, current_positions: list) -> bool:
        """
        Check if we can open a new position
        
        Args:
            current_positions: List of current open positions
        
        Returns:
            True if we can open new position
        """
        return len(current_positions) < config.MAX_OPEN_POSITIONS
    
    def is_symbol_in_position(self, symbol: str, positions: list) -> bool:
        """
        Check if we already have a position in this symbol
        
        Args:
            symbol: Trading pair
            positions: List of current positions
        
        Returns:
            True if already in position
        """
        for pos in positions:
            if pos['symbol'] == symbol and float(pos.get('positionAmt', 0)) != 0:
                return True
        return False
    
    def validate_trade(self, trade_params: Dict) -> Tuple[bool, str]:
        """
        Validate trade parameters before execution
        
        Args:
            trade_params: Trade parameters dictionary
        
        Returns:
            Tuple of (is_valid, reason)
        """
        quantity = trade_params['quantity']
        entry_price = trade_params['entry_price']
        
        # Get capital
        capital = self.get_capital()
        
        # Check minimum quantity
        if quantity <= 0:
            return False, "Quantity too small"
        
        # Check if we have enough margin
        required_margin = (quantity * entry_price) / config.LEVERAGE
        if required_margin > capital:
            return False, f"Insufficient capital. Need {required_margin:.2f} USDT"
        
        return True, "OK"


# Test when run directly
if __name__ == "__main__":
    print("Testing Risk Manager Module...")
    print(f"Capital: {config.TOTAL_CAPITAL_USDT} USDT")
    print(f"Leverage: {config.LEVERAGE}x")
    print(f"Initial Margin per Trade: {config.INITIAL_MARGIN_PER_TRADE} USDT")
    
    # Mock client
    class MockClient:
        def round_price(self, symbol, price):
            return round(price, 2)
        def round_quantity(self, symbol, qty):
            return round(qty, 3)
        def get_symbol_info(self, symbol):
            return {'pricePrecision': 2, 'quantityPrecision': 3}
    
    rm = RiskManager(MockClient())
    
    # Test trade params calculation
    params = rm.calculate_trade_params(
        symbol="BTCUSDT",
        side="BUY",
        entry_price=50000.0,
        atr=500.0
    )
    
    print(f"\n✅ Quantity: {params['quantity']} BTC")
    print(f"✅ Position Value: ${params['quantity'] * params['entry_price']:.2f}")
    print(f"✅ Initial Margin: ${params['initial_margin']:.2f}")
    print(f"✅ Stop Loss: ${params['stop_loss']}")
    print(f"✅ Take Profit: ${params['take_profit']}")
    print(f"✅ Risk: ${params['risk_usdt']:.2f}")
    print(f"✅ Reward: ${params['reward_usdt']:.2f}")
    
    # Validate
    is_valid, reason = rm.validate_trade(params)
    print(f"✅ Valid: {is_valid} - {reason}")
    
    print("\n✅ All risk manager tests passed!")
