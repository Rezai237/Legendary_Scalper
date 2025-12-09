"""
Grok AI Client Module
Integrates xAI Grok for market regime detection and news analysis
"""

import requests
import json
from typing import Dict, Optional, List
import config
from logger import logger


class GrokClient:
    """Client for xAI Grok API"""
    
    def __init__(self):
        self.api_key = config.GROK_API_KEY
        self.model = config.GROK_MODEL
        self.base_url = config.GROK_BASE_URL
        
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        })
        
        # State tracking
        self.current_regime = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL
        self.regime_confidence = 0.5
        self.last_regime_check = 0
        self.last_news_check = 0
        self.bullish_coins = []
        self.bearish_coins = []
        
        logger.info("Grok AI client initialized")
    
    def _call_grok(self, prompt: str, max_tokens: int = 500) -> Optional[str]:
        """Make API call to Grok"""
        try:
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a professional crypto market analyst. Give concise, actionable analysis. Always respond in JSON format when asked."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3
            }
            
            response = self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=30
            )
            
            response.raise_for_status()
            data = response.json()
            
            return data['choices'][0]['message']['content']
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Grok API error: {e}")
            return None
        except (KeyError, IndexError) as e:
            logger.error(f"Grok response parse error: {e}")
            return None
    
    def analyze_market_regime(self, market_data: Dict) -> Dict:
        """
        Analyze current market regime (bullish/bearish/neutral)
        Called every 30 minutes
        
        Args:
            market_data: Dict with top gainers, losers, BTC price, etc.
        
        Returns:
            Dict with regime, confidence, and recommendation
        """
        prompt = f"""
Analyze the current crypto market and determine the market regime.

Market Data:
- BTC 24h Change: {market_data.get('btc_change', 'N/A')}%
- ETH 24h Change: {market_data.get('eth_change', 'N/A')}%
- Top Gainers: {market_data.get('top_gainers', [])}
- Top Losers: {market_data.get('top_losers', [])}
- Overall Market Sentiment: {market_data.get('sentiment', 'N/A')}

Respond in JSON format:
{{
    "regime": "BULLISH" or "BEARISH" or "NEUTRAL",
    "confidence": 0.0 to 1.0,
    "reason": "brief explanation",
    "recommendation": "LONG_ONLY" or "SHORT_ONLY" or "BOTH" or "NO_TRADE"
}}
"""
        
        response = self._call_grok(prompt, max_tokens=300)
        
        if response:
            try:
                # Extract JSON from response
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    result = json.loads(response[json_start:json_end])
                    
                    self.current_regime = result.get('regime', 'NEUTRAL')
                    self.regime_confidence = result.get('confidence', 0.5)
                    
                    logger.info(f"🤖 Grok Market Regime: {self.current_regime} ({self.regime_confidence:.0%})")
                    return result
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Grok response: {e}")
        
        return {
            "regime": "NEUTRAL",
            "confidence": 0.5,
            "reason": "Analysis failed",
            "recommendation": "BOTH"
        }
    
    def analyze_news_sentiment(self) -> Dict:
        """
        Analyze daily crypto news and sentiment
        Called once per day
        
        Returns:
            Dict with bullish/bearish coins and overall sentiment
        """
        prompt = """
Analyze the current crypto market news and sentiment for today.

Based on recent news, events, and market sentiment:

1. Which coins have BULLISH news/catalysts?
2. Which coins have BEARISH news/warnings?
3. What is the overall market outlook?

Respond in JSON format:
{
    "overall_sentiment": "BULLISH" or "BEARISH" or "NEUTRAL",
    "bullish_coins": ["BTCUSDT", "ETHUSDT", ...],
    "bearish_coins": ["XXXUSDT", ...],
    "key_events": ["brief event 1", "brief event 2"],
    "risk_level": "LOW" or "MEDIUM" or "HIGH"
}
"""
        
        response = self._call_grok(prompt, max_tokens=500)
        
        if response:
            try:
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    result = json.loads(response[json_start:json_end])
                    
                    self.bullish_coins = result.get('bullish_coins', [])
                    self.bearish_coins = result.get('bearish_coins', [])
                    
                    logger.info(f"🤖 Grok News Analysis: {result.get('overall_sentiment', 'N/A')}")
                    logger.info(f"   Bullish: {self.bullish_coins[:5]}")
                    logger.info(f"   Bearish: {self.bearish_coins[:5]}")
                    
                    return result
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Grok news response: {e}")
        
        return {
            "overall_sentiment": "NEUTRAL",
            "bullish_coins": [],
            "bearish_coins": [],
            "key_events": [],
            "risk_level": "MEDIUM"
        }
    
    def should_trade_symbol(self, symbol: str, signal_type: str) -> bool:
        """
        Check if trading is allowed based on Grok analysis
        
        Args:
            symbol: Trading pair
            signal_type: "BUY" or "SELL"
        
        Returns:
            True if trading is allowed
        """
        if not config.GROK_ENABLED:
            return True
        
        # Check market regime
        if self.current_regime == "BULLISH" and signal_type == "SELL":
            if self.regime_confidence > 0.7:
                logger.debug(f"Grok: Skipping SELL in BULLISH market ({symbol})")
                return False
        
        if self.current_regime == "BEARISH" and signal_type == "BUY":
            if self.regime_confidence > 0.7:
                logger.debug(f"Grok: Skipping BUY in BEARISH market ({symbol})")
                return False
        
        # Check bearish coins list
        if symbol in self.bearish_coins and signal_type == "BUY":
            logger.debug(f"Grok: {symbol} is bearish, skipping BUY")
            return False
        
        return True
    
    def get_regime_info(self) -> Dict:
        """Get current market regime information"""
        return {
            "regime": self.current_regime,
            "confidence": self.regime_confidence,
            "bullish_coins": self.bullish_coins,
            "bearish_coins": self.bearish_coins
        }
    
    def analyze_coin_sentiment(self, symbol: str, pump_percent: float) -> Dict:
        """
        Analyze sentiment for a specific pumped coin to detect FOMO/Peak
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            pump_percent: Current 24h pump percentage
        
        Returns:
            Dict with sentiment, fomo_level, should_short
        """
        coin_name = symbol.replace('USDT', '')
        
        prompt = f"""
You are analyzing social media and market sentiment for a crypto coin that just pumped significantly.

Coin: {coin_name}
24h Pump: +{pump_percent:.1f}%

Based on typical market behavior and sentiment patterns for coins with this level of pump:

1. What is the likely social media sentiment? (EXTREME_FOMO, HIGH_FOMO, MODERATE, SKEPTICAL)
2. Is this likely near the top/peak of the pump?
3. What is the probability of a significant correction in the next 1-4 hours?

Respond in JSON format:
{{
    "sentiment": "EXTREME_FOMO" or "HIGH_FOMO" or "MODERATE" or "SKEPTICAL",
    "fomo_level": 0 to 100,
    "near_peak": true or false,
    "correction_probability": 0 to 100,
    "should_short": true or false,
    "reason": "brief explanation",
    "expected_correction_percent": 5 to 30
}}
"""
        
        response = self._call_grok(prompt, max_tokens=400)
        
        if response:
            try:
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    result = json.loads(response[json_start:json_end])
                    
                    fomo_level = result.get('fomo_level', 50)
                    should_short = result.get('should_short', False)
                    
                    logger.info(f"🤖 Grok Sentiment for {symbol}:")
                    logger.info(f"   📊 FOMO Level: {fomo_level}%")
                    logger.info(f"   🎯 Near Peak: {result.get('near_peak', 'N/A')}")
                    logger.info(f"   💡 Should SHORT: {should_short}")
                    
                    return result
                    
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse Grok sentiment: {e}")
        
        # Default response if Grok fails
        return {
            "sentiment": "MODERATE",
            "fomo_level": 50,
            "near_peak": pump_percent > 50,
            "correction_probability": min(pump_percent, 70),
            "should_short": pump_percent > 30,
            "reason": "Default analysis based on pump level",
            "expected_correction_percent": min(pump_percent * 0.3, 20)
        }
    
    def is_good_short_entry(self, symbol: str, pump_percent: float) -> Dict:
        """
        Quick check if a pumped coin is good for SHORT entry
        
        Returns:
            Dict with is_good, confidence, reason
        """
        # Use Grok for high pumps only (save API calls)
        if pump_percent < 40:
            # For lower pumps, use default logic
            return {
                'is_good': pump_percent >= 30,
                'confidence': 60 if pump_percent >= 30 else 40,
                'reason': f'Pump {pump_percent:.1f}% - standard entry'
            }
        
        # For high pumps, ask Grok
        sentiment = self.analyze_coin_sentiment(symbol, pump_percent)
        
        return {
            'is_good': sentiment.get('should_short', False),
            'confidence': sentiment.get('correction_probability', 50),
            'reason': sentiment.get('reason', 'Grok analysis'),
            'fomo_level': sentiment.get('fomo_level', 50),
            'expected_correction': sentiment.get('expected_correction_percent', 10)
        }


# Test when run directly
if __name__ == "__main__":
    client = GrokClient()
    
    # Test market regime
    test_data = {
        "btc_change": 2.5,
        "eth_change": 3.1,
        "top_gainers": ["SOLUSDT +8%", "AVAXUSDT +6%"],
        "top_losers": ["DOGEUSDT -3%"],
        "sentiment": "Positive"
    }
    
    result = client.analyze_market_regime(test_data)
    print(f"Market Regime: {result}")
