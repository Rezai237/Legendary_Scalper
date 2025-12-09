"""
Binance API Client for USDT-M Futures
Handles all API communication with Binance
"""

import hashlib
import hmac
import time
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode

import requests

import config
from logger import logger


class BinanceClient:
    """Client for Binance USDT-M Futures API"""
    
    def __init__(self):
        self.api_key = config.API_KEY
        self.api_secret = config.API_SECRET
        self.base_url = config.get_base_url()
        
        self.session = requests.Session()
        self.session.headers.update({
            'X-MBX-APIKEY': self.api_key
        })
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 0.1  # 100ms between requests
    
    def _get_timestamp(self) -> int:
        """Get current timestamp in milliseconds"""
        return int(time.time() * 1000)
    
    def _sign(self, params: Dict) -> str:
        """Generate HMAC SHA256 signature"""
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _rate_limit(self):
        """Simple rate limiting"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def _request(self, method: str, endpoint: str, params: Dict = None, 
                 signed: bool = False) -> Any:
        """Make API request with error handling"""
        
        self._rate_limit()
        
        url = f"{self.base_url}{endpoint}"
        params = params or {}
        
        if signed:
            params['timestamp'] = self._get_timestamp()
            params['signature'] = self._sign(params)
        
        try:
            if method == 'GET':
                response = self.session.get(url, params=params)
            elif method == 'POST':
                response = self.session.post(url, params=params)
            elif method == 'DELETE':
                response = self.session.delete(url, params=params)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP Error: {e}"
            try:
                error_data = response.json()
                error_code = error_data.get('code')
                error_msg = f"API Error {error_code}: {error_data.get('msg')}"
                # Don't log harmless errors
                if error_code != -4046:  # "No need to change margin type"
                    logger.error(error_msg)
            except:
                logger.error(error_msg)
            raise Exception(error_msg)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise
    
    # =========================================================================
    # Market Data Endpoints
    # =========================================================================
    
    def get_server_time(self) -> int:
        """Get server time"""
        data = self._request('GET', '/fapi/v1/time')
        return data['serverTime']
    
    def get_exchange_info(self) -> Dict:
        """Get exchange information"""
        return self._request('GET', '/fapi/v1/exchangeInfo')
    
    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List:
        """
        Get kline/candlestick data
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            interval: Kline interval (1m, 3m, 5m, 15m, etc.)
            limit: Number of klines (default 100, max 1500)
        
        Returns:
            List of klines [open_time, open, high, low, close, volume, ...]
        """
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        return self._request('GET', '/fapi/v1/klines', params)
    
    def get_ticker_24h(self, symbol: str = None) -> Any:
        """Get 24h ticker statistics"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._request('GET', '/fapi/v1/ticker/24hr', params)
    
    def get_mark_price(self, symbol: str = None) -> Any:
        """Get mark price"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._request('GET', '/fapi/v1/premiumIndex', params)
    
    def get_top_pairs_by_volume(self, count: int = 30) -> List[str]:
        """Get top trading pairs sorted by 24h volume"""
        tickers = self.get_ticker_24h()
        
        # Filter USDT perpetual pairs only
        usdt_pairs = [
            t for t in tickers 
            if t['symbol'].endswith(config.QUOTE_ASSET) 
            and not any(x in t['symbol'] for x in ['_', 'DEFI', 'INDEX'])
        ]
        
        # Sort by quote volume (USDT volume)
        sorted_pairs = sorted(
            usdt_pairs, 
            key=lambda x: float(x['quoteVolume']), 
            reverse=True
        )
        
        return [p['symbol'] for p in sorted_pairs[:count]]
    
    def get_top_pairs_by_volatility(self, count: int = 30) -> List[str]:
        """
        Get top trading pairs sorted by 24h price volatility
        
        Args:
            count: Number of pairs to return
        
        Returns:
            List of symbols sorted by volatility (highest first)
        """
        tickers = self.get_ticker_24h()
        
        # Filter USDT perpetual pairs only
        usdt_pairs = [
            t for t in tickers 
            if t['symbol'].endswith(config.QUOTE_ASSET) 
            and not any(x in t['symbol'] for x in ['_', 'DEFI', 'INDEX'])
        ]
        
        # Apply blacklist filter
        blacklist = getattr(config, 'BLACKLIST', [])
        usdt_pairs = [
            t for t in usdt_pairs 
            if t['symbol'] not in blacklist
        ]
        
        # Filter by minimum volatility
        min_volatility = getattr(config, 'MIN_VOLATILITY_PERCENT', 1.0)
        volatile_pairs = [
            t for t in usdt_pairs
            if abs(float(t.get('priceChangePercent', 0))) >= min_volatility
        ]
        
        # Sort by absolute price change (volatility)
        sorted_pairs = sorted(
            volatile_pairs, 
            key=lambda x: abs(float(x.get('priceChangePercent', 0))), 
            reverse=True
        )
        
        logger.info(f"Found {len(sorted_pairs)} volatile pairs (min {min_volatility}%)")
        
        return [p['symbol'] for p in sorted_pairs[:count]]
    
    # =========================================================================
    # Account Endpoints
    # =========================================================================
    
    def get_account_info(self) -> Dict:
        """Get account information"""
        return self._request('GET', '/fapi/v2/account', signed=True)
    
    def get_balance(self) -> List[Dict]:
        """Get account balance"""
        return self._request('GET', '/fapi/v2/balance', signed=True)
    
    def get_usdt_balance(self) -> float:
        """Get USDT balance"""
        balances = self.get_balance()
        for balance in balances:
            if balance['asset'] == 'USDT':
                return float(balance['availableBalance'])
        return 0.0
    
    def get_positions(self) -> List[Dict]:
        """Get all open positions"""
        account = self.get_account_info()
        positions = account.get('positions', [])
        
        # Filter only positions with non-zero amount
        open_positions = [
            p for p in positions 
            if float(p.get('positionAmt', 0)) != 0
        ]
        
        return open_positions
    
    # =========================================================================
    # Trading Endpoints
    # =========================================================================
    
    def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """Set leverage for a symbol"""
        params = {
            'symbol': symbol,
            'leverage': leverage
        }
        return self._request('POST', '/fapi/v1/leverage', params, signed=True)
    
    def set_margin_type(self, symbol: str, margin_type: str) -> Dict:
        """Set margin type (ISOLATED or CROSSED)"""
        params = {
            'symbol': symbol,
            'marginType': margin_type
        }
        try:
            return self._request('POST', '/fapi/v1/marginType', params, signed=True)
        except Exception as e:
            # Already set to this margin type
            if 'No need to change margin type' in str(e):
                return {'msg': 'Already set'}
            raise
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """
        Place a market order
        
        Args:
            symbol: Trading pair
            side: BUY or SELL
            quantity: Order quantity
        """
        params = {
            'symbol': symbol,
            'side': side,
            'type': 'MARKET',
            'quantity': quantity
        }
        return self._request('POST', '/fapi/v1/order', params, signed=True)
    
    def place_stop_loss(self, symbol: str, side: str, quantity: float, 
                        stop_price: float) -> Dict:
        """Place a stop-loss order"""
        params = {
            'symbol': symbol,
            'side': side,
            'type': 'STOP_MARKET',
            'stopPrice': stop_price,
            'closePosition': 'true',
            'workingType': 'MARK_PRICE'
        }
        return self._request('POST', '/fapi/v1/order', params, signed=True)
    
    def place_take_profit(self, symbol: str, side: str, quantity: float,
                          stop_price: float) -> Dict:
        """Place a take-profit order"""
        params = {
            'symbol': symbol,
            'side': side,
            'type': 'TAKE_PROFIT_MARKET',
            'stopPrice': stop_price,
            'closePosition': 'true',
            'workingType': 'MARK_PRICE'
        }
        return self._request('POST', '/fapi/v1/order', params, signed=True)
    
    def cancel_all_orders(self, symbol: str) -> Dict:
        """Cancel all open orders for a symbol"""
        params = {'symbol': symbol}
        return self._request('DELETE', '/fapi/v1/allOpenOrders', params, signed=True)
    
    def get_open_orders(self, symbol: str = None) -> List[Dict]:
        """Get all open orders"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._request('GET', '/fapi/v1/openOrders', params, signed=True)
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Get symbol trading rules"""
        exchange_info = self.get_exchange_info()
        for s in exchange_info['symbols']:
            if s['symbol'] == symbol:
                return s
        return None
    
    def get_price_precision(self, symbol: str) -> int:
        """Get price precision for a symbol"""
        info = self.get_symbol_info(symbol)
        if info:
            return info.get('pricePrecision', 2)
        return 2
    
    def get_quantity_precision(self, symbol: str) -> int:
        """Get quantity precision for a symbol"""
        info = self.get_symbol_info(symbol)
        if info:
            return info.get('quantityPrecision', 3)
        return 3
    
    def round_price(self, symbol: str, price: float) -> float:
        """Round price to symbol precision"""
        precision = self.get_price_precision(symbol)
        return round(price, precision)
    
    def round_quantity(self, symbol: str, quantity: float) -> float:
        """Round quantity to symbol precision"""
        precision = self.get_quantity_precision(symbol)
        return round(quantity, precision)


# Test connection when module is run directly
if __name__ == "__main__":
    print("Testing Binance Client...")
    client = BinanceClient()
    
    try:
        server_time = client.get_server_time()
        print(f"✅ Server Time: {server_time}")
        
        top_pairs = client.get_top_pairs_by_volume(5)
        print(f"✅ Top 5 Pairs: {top_pairs}")
        
        balance = client.get_usdt_balance()
        print(f"✅ USDT Balance: {balance}")
        
        print("\n✅ All tests passed!")
    except Exception as e:
        print(f"❌ Error: {e}")
