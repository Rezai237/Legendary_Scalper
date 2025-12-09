"""
Chart Vision Module - Enhanced with Smart Browser AI
Generates candlestick charts and uses Grok Vision for professional analysis
"""

import os
import io
import base64
import time
import json
import re
from datetime import datetime
from typing import Dict, Optional, List
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from mplfinance.original_flavor import candlestick_ohlc

import config
from logger import logger


# =============================================================================
# PROFESSIONAL CHART ANALYSIS PROMPTS (from smart_browser)
# =============================================================================

CHART_ANALYSIS_PROMPT = """
You are a professional crypto technical analyst.

This is a {symbol} candlestick chart from Binance Futures.

Analyze the chart completely:

1. **Current Trend**: Bullish/Bearish/Neutral
2. **Chart Patterns**: (Triangle, Head & Shoulders, Double Top/Bottom, Flag, Wedge...)
3. **Key Levels**:
   - Support levels (where price bounced)
   - Resistance levels (where price rejected)
4. **Candlestick Patterns**: What do the recent candles indicate?
5. **Volume**: Volume trend analysis
6. **Final Signal**: BUY / SELL / WAIT

Respond ONLY in this exact JSON format:
{{
    "trend": "bullish|bearish|neutral",
    "trend_strength": 75,
    "patterns": ["pattern1", "pattern2"],
    "support_levels": [95000, 92000],
    "resistance_levels": [100000, 105000],
    "current_price": {current_price},
    "signal": "BUY|SELL|WAIT",
    "entry_price": 98500,
    "stop_loss": 95000,
    "take_profit": 104000,
    "risk_reward_ratio": 2.5,
    "confidence": 75,
    "reasoning": "Complete analysis explanation",
    "warnings": ["warning1", "warning2"]
}}

⚠️ Return ONLY valid JSON, no extra text!
"""

CANDLESTICK_PATTERNS_PROMPT = """
Analyze the last 5-10 candles in this chart:

1. **Candle Types**: What type is each candle?
2. **Combined Patterns**: Any patterns formed?
3. **Signal**: Bullish or Bearish?

Important patterns to identify:
- Doji (indecision)
- Hammer / Hanging Man (reversal)
- Engulfing (strong reversal)
- Morning/Evening Star (reversal)
- Three White Soldiers / Black Crows (continuation)
- Pin Bar (rejection)
- Inside Bar (consolidation)

Return JSON:
{{
    "main_pattern": "pattern name or none",
    "pattern_type": "reversal|continuation|neutral",
    "signal": "bullish|bearish|neutral",
    "strength": 75,
    "entry_suggestion": "price or null",
    "stop_loss_suggestion": "price or null",
    "description": "brief explanation"
}}
"""


class ChartVision:
    """Chart generation and Grok Vision analysis - Enhanced"""
    
    def __init__(self, grok_client=None):
        self.grok = grok_client
        self.chart_dir = os.path.join(os.path.dirname(__file__), 'charts')
        os.makedirs(self.chart_dir, exist_ok=True)
        
        # Cache for analysis results
        self.analysis_cache = {}
        self.last_analysis_time = {}
        
        # Settings
        self.analysis_interval = getattr(config, 'VISION_ANALYSIS_INTERVAL', 3) * 60
        
        logger.info("📊 Enhanced Chart Vision module initialized")
    
    def generate_chart(self, symbol: str, df: pd.DataFrame, timeframe: str = '15m') -> Optional[str]:
        """
        Generate professional candlestick chart with indicators
        """
        try:
            if len(df) < 20:
                return None
            
            # More candles for better analysis
            df = df.tail(60).copy()
            df['datetime'] = pd.to_datetime(df['open_time'], unit='ms')
            df['date_num'] = mdates.date2num(df['datetime'])
            
            # Create figure with better size
            fig, axes = plt.subplots(3, 1, figsize=(14, 10), 
                                     gridspec_kw={'height_ratios': [4, 1, 1]})
            fig.patch.set_facecolor('#1a1a2e')
            
            ax_price = axes[0]
            ax_volume = axes[1]
            ax_rsi = axes[2]
            
            for ax in axes:
                ax.set_facecolor('#1a1a2e')
                ax.tick_params(colors='white')
                ax.grid(True, alpha=0.2, color='gray')
            
            # Candlestick chart
            ohlc = df[['date_num', 'open', 'high', 'low', 'close']].values
            candlestick_ohlc(ax_price, ohlc, width=0.0004, colorup='#00ff88', colordown='#ff4444')
            
            # Add EMA lines
            if 'ema_fast' in df.columns:
                ax_price.plot(df['date_num'], df['ema_fast'], color='#ffcc00', linewidth=1.5, label=f'EMA{config.EMA_FAST_PERIOD}')
            if 'ema_slow' in df.columns:
                ax_price.plot(df['date_num'], df['ema_slow'], color='#00ccff', linewidth=1.5, label=f'EMA{config.EMA_SLOW_PERIOD}')
            
            # Bollinger Bands if available
            if 'bb_upper' in df.columns:
                ax_price.plot(df['date_num'], df['bb_upper'], color='#ff66ff', linewidth=0.8, linestyle='--', alpha=0.7)
                ax_price.plot(df['date_num'], df['bb_lower'], color='#ff66ff', linewidth=0.8, linestyle='--', alpha=0.7)
                ax_price.fill_between(df['date_num'], df['bb_upper'], df['bb_lower'], alpha=0.1, color='#ff66ff')
            
            # Current price line
            current_price = df['close'].iloc[-1]
            ax_price.axhline(y=current_price, color='white', linestyle='--', alpha=0.5, linewidth=0.8)
            ax_price.annotate(f'{current_price:.4f}', xy=(df['date_num'].iloc[-1], current_price),
                            xytext=(5, 0), textcoords='offset points', color='white', fontsize=9)
            
            # Volume bars with colors
            colors = ['#00ff88' if c >= o else '#ff4444' 
                      for c, o in zip(df['close'], df['open'])]
            ax_volume.bar(df['date_num'], df['volume'], width=0.0003, color=colors, alpha=0.7)
            ax_volume.set_ylabel('Volume', color='white', fontsize=8)
            
            # RSI if available
            if 'rsi' in df.columns:
                ax_rsi.plot(df['date_num'], df['rsi'], color='#ffcc00', linewidth=1.5)
                ax_rsi.axhline(y=70, color='red', linestyle='--', alpha=0.5, linewidth=0.8)
                ax_rsi.axhline(y=30, color='green', linestyle='--', alpha=0.5, linewidth=0.8)
                ax_rsi.axhline(y=50, color='gray', linestyle='--', alpha=0.3, linewidth=0.5)
                ax_rsi.set_ylabel('RSI', color='white', fontsize=8)
                ax_rsi.set_ylim(0, 100)
            
            # Format axes
            for ax in axes:
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            
            # Title
            ax_price.set_title(f'{symbol} - {timeframe} Chart | {datetime.now().strftime("%Y-%m-%d %H:%M")}', 
                              color='white', fontsize=12, fontweight='bold')
            ax_price.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white', fontsize=8)
            
            plt.tight_layout()
            
            # Convert to base64
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', facecolor='#1a1a2e', edgecolor='none', dpi=120)
            buffer.seek(0)
            image_bytes = buffer.read()
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            plt.close(fig)
            
            # Also save to file for debugging
            save_path = os.path.join(self.chart_dir, f'{symbol}_{timeframe}.png')
            with open(save_path, 'wb') as f:
                f.write(image_bytes)
            
            logger.info(f"📊 Chart saved: {symbol}_{timeframe}.png")
            
            return image_base64
            
        except Exception as e:
            logger.error(f"Chart generation failed for {symbol}: {e}")
            plt.close('all')
            return None
    
    def analyze_chart_with_vision(self, symbol: str, image_base64: str, current_price: float) -> Optional[Dict]:
        """
        Send chart to Grok Vision for professional analysis
        """
        if not self.grok:
            return None
        
        try:
            import requests
            
            prompt = CHART_ANALYSIS_PROMPT.format(
                symbol=symbol,
                current_price=current_price
            )

            payload = {
                "model": config.GROK_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 1000,
                "temperature": 0.2
            }
            
            headers = {
                'Authorization': f'Bearer {config.GROK_API_KEY}',
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                f"{config.GROK_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
                timeout=45
            )
            
            response.raise_for_status()
            data = response.json()
            content = data['choices'][0]['message']['content']
            
            # Parse JSON response
            result = self._extract_json(content)
            
            if result:
                # Cache result
                self.analysis_cache[symbol] = result
                self.last_analysis_time[symbol] = time.time()
                
                # Log analysis
                signal = result.get('signal', 'WAIT')
                confidence = result.get('confidence', 0)
                pattern = result.get('patterns', ['None'])[0] if result.get('patterns') else 'None'
                
                logger.info(f"🤖 Vision Analysis: {symbol}")
                logger.info(f"   📊 Trend: {result.get('trend', 'N/A')} | Signal: {signal}")
                logger.info(f"   🎯 Pattern: {pattern} | Confidence: {confidence}%")
                
                if result.get('support_levels'):
                    logger.info(f"   📉 Support: {result.get('support_levels', [])}")
                if result.get('resistance_levels'):
                    logger.info(f"   📈 Resistance: {result.get('resistance_levels', [])}")
                
                return result
            else:
                logger.warning(f"Could not parse Vision response for {symbol}")
                return {"raw_response": content}
                
        except Exception as e:
            logger.debug(f"Vision analysis failed for {symbol}: {e}")
            return None
    
    def _extract_json(self, text: str) -> Optional[dict]:
        """Extract JSON from response text"""
        # Try direct parse first
        try:
            return json.loads(text)
        except:
            pass
        
        # Try to find JSON in code blocks
        patterns = [
            r'```json\s*([\s\S]*?)\s*```',
            r'```\s*([\s\S]*?)\s*```',
            r'\{[\s\S]*\}'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    json_str = match.group(1) if '```' in pattern else match.group(0)
                    return json.loads(json_str)
                except:
                    continue
        
        return None
    
    def should_analyze(self, symbol: str) -> bool:
        """Check if symbol needs new analysis"""
        if symbol not in self.last_analysis_time:
            return True
        
        elapsed = time.time() - self.last_analysis_time[symbol]
        return elapsed >= self.analysis_interval
    
    def get_cached_analysis(self, symbol: str) -> Optional[Dict]:
        """Get cached analysis for symbol"""
        return self.analysis_cache.get(symbol)
    
    def get_vision_sl_tp(self, symbol: str, side: str, entry_price: float) -> Dict:
        """
        Get SL/TP from vision analysis
        Uses support/resistance levels for precise placement
        """
        analysis = self.get_cached_analysis(symbol)
        
        if not analysis:
            return {'stop_loss': None, 'take_profit': None, 'vision_used': False}
        
        confidence = analysis.get('confidence', 0)
        min_confidence = getattr(config, 'VISION_MIN_CONFIDENCE', 0.6) * 100
        
        if confidence < min_confidence:
            return {'stop_loss': None, 'take_profit': None, 'vision_used': False, 
                    'reason': f'Low confidence: {confidence}%'}
        
        # Get SL/TP from analysis (Grok may provide directly)
        sl = analysis.get('stop_loss')
        tp = analysis.get('take_profit')
        
        supports = [float(s) for s in analysis.get('support_levels', []) if s]
        resistances = [float(r) for r in analysis.get('resistance_levels', []) if r]
        
        # Calculate SL/TP based on trade direction
        if side == 'BUY':
            # BUY: SL below entry (support), TP above entry (resistance)
            if not sl and supports:
                valid_supports = [s for s in supports if s < entry_price]
                if valid_supports:
                    sl = max(valid_supports) * 0.997  # Just below support
            
            if not tp and resistances:
                valid_resistances = [r for r in resistances if r > entry_price]
                if valid_resistances:
                    tp = min(valid_resistances) * 0.998  # Just below resistance
        
        else:  # SELL
            # SELL: SL above entry (resistance), TP below entry (support)
            if not sl and resistances:
                valid_resistances = [r for r in resistances if r > entry_price]
                if valid_resistances:
                    sl = min(valid_resistances) * 1.003  # Just above resistance
            
            if not tp and supports:
                valid_supports = [s for s in supports if s < entry_price]
                if valid_supports:
                    tp = max(valid_supports) * 1.002  # Just above support
        
        # Final validation
        if side == 'BUY':
            if sl and sl >= entry_price:
                sl = None
            if tp and tp <= entry_price:
                tp = None
        else:  # SELL
            if sl and sl <= entry_price:
                sl = None
            if tp and tp >= entry_price:
                tp = None
        
        return {
            'stop_loss': sl,
            'take_profit': tp,
            'vision_used': sl is not None or tp is not None,
            'pattern': analysis.get('patterns', ['None'])[0] if analysis.get('patterns') else None,
            'trend': analysis.get('trend'),
            'confidence': confidence,
            'signal': analysis.get('signal'),
            'reasoning': analysis.get('reasoning', '')[:100]
        }


if __name__ == "__main__":
    print("Enhanced Chart Vision module loaded successfully!")
