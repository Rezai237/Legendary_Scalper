"""
Order Executor Module
Handles order placement and management
"""

from typing import Dict, Optional
import config
from logger import logger, log_trade


class OrderExecutor:
    """Executes and manages orders on Binance Futures"""
    
    def __init__(self, client):
        self.client = client
        self.pending_orders = {}  # Track orders by symbol
    
    def setup_symbol(self, symbol: str) -> bool:
        """
        Setup symbol for trading (leverage & margin type)
        
        Args:
            symbol: Trading pair
        
        Returns:
            True if setup successful
        """
        try:
            # Set leverage
            self.client.set_leverage(symbol, config.LEVERAGE)
            logger.debug(f"Set leverage for {symbol}: {config.LEVERAGE}x")
            
            # Set margin type (ignore error if already set)
            try:
                self.client.set_margin_type(symbol, config.MARGIN_TYPE)
                logger.debug(f"Set margin type for {symbol}: {config.MARGIN_TYPE}")
            except Exception:
                pass  # Already set, ignore
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup {symbol}: {e}")
            return False
    
    def execute_entry(self, trade_params: Dict) -> Optional[Dict]:
        """
        Execute a market entry order with stop-loss and take-profit
        
        Args:
            trade_params: Trade parameters from RiskManager
        
        Returns:
            Order response or None if failed
        """
        symbol = trade_params['symbol']
        side = trade_params['side']
        quantity = trade_params['quantity']
        stop_loss = trade_params['stop_loss']
        take_profit = trade_params['take_profit']
        
        try:
            # Setup symbol first
            self.setup_symbol(symbol)
            
            # Place market order
            logger.info(f"Placing {side} order for {symbol}: {quantity} @ Market")
            
            entry_order = self.client.place_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity
            )
            
            if not entry_order or 'orderId' not in entry_order:
                logger.error(f"Failed to place entry order for {symbol}")
                return None
            
            order_id = entry_order['orderId']
            entry_price = float(entry_order.get('avgPrice', trade_params['entry_price']))
            
            logger.info(f"✅ Entry order filled: {symbol} {side} {quantity} @ {entry_price}")
            
            # Place stop loss
            sl_side = "SELL" if side == "BUY" else "BUY"
            try:
                sl_order = self.client.place_stop_loss(
                    symbol=symbol,
                    side=sl_side,
                    quantity=quantity,
                    stop_price=stop_loss
                )
                logger.info(f"✅ Stop Loss placed: {symbol} @ {stop_loss}")
            except Exception as e:
                logger.warning(f"Failed to place SL for {symbol}: {e}")
            
            # Place take profit
            try:
                tp_order = self.client.place_take_profit(
                    symbol=symbol,
                    side=sl_side,
                    quantity=quantity,
                    stop_price=take_profit
                )
                logger.info(f"✅ Take Profit placed: {symbol} @ {take_profit}")
            except Exception as e:
                logger.warning(f"Failed to place TP for {symbol}: {e}")
            
            # Log trade
            log_trade(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                order_id=str(order_id)
            )
            
            return {
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'order_id': order_id
            }
            
        except Exception as e:
            logger.error(f"Failed to execute entry for {symbol}: {e}")
            return None
    
    def close_position(self, symbol: str, position: Dict) -> Optional[Dict]:
        """
        Close an existing position
        
        Args:
            symbol: Trading pair
            position: Position info dict
        
        Returns:
            Order response or None
        """
        try:
            position_amt = float(position.get('positionAmt', 0))
            
            if position_amt == 0:
                return None
            
            # Determine side (opposite of position)
            side = "SELL" if position_amt > 0 else "BUY"
            quantity = abs(position_amt)
            
            # Cancel all pending orders first
            self.client.cancel_all_orders(symbol)
            
            # Close position with market order
            order = self.client.place_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity
            )
            
            logger.info(f"✅ Position closed: {symbol} {side} {quantity}")
            
            return order
            
        except Exception as e:
            logger.error(f"Failed to close position for {symbol}: {e}")
            return None
    
    def close_all_positions(self) -> int:
        """
        Close all open positions
        
        Returns:
            Number of positions closed
        """
        closed_count = 0
        
        try:
            positions = self.client.get_positions()
            
            for position in positions:
                symbol = position['symbol']
                result = self.close_position(symbol, position)
                if result:
                    closed_count += 1
            
        except Exception as e:
            logger.error(f"Error closing positions: {e}")
        
        return closed_count
    
    def get_open_orders_count(self, symbol: str = None) -> int:
        """Get count of open orders"""
        try:
            orders = self.client.get_open_orders(symbol)
            return len(orders)
        except:
            return 0
    
    def cancel_symbol_orders(self, symbol: str) -> bool:
        """Cancel all orders for a symbol"""
        try:
            self.client.cancel_all_orders(symbol)
            logger.info(f"Cancelled all orders for {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel orders for {symbol}: {e}")
            return False


# Test when run directly
if __name__ == "__main__":
    print("Testing Order Executor Module...")
    print("(Requires actual API connection)")
    
    from binance_client import BinanceClient
    
    try:
        client = BinanceClient()
        executor = OrderExecutor(client)
        
        # Test setup
        success = executor.setup_symbol("BTCUSDT")
        print(f"✅ Symbol setup: {success}")
        
        # Get open orders count
        count = executor.get_open_orders_count()
        print(f"✅ Open orders: {count}")
        
        print("\n✅ Order executor ready!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
