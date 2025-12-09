# 🦅 Legendary Scalper Bot v2.0 (AI-Powered)

An advanced, fully automated crypto trading bot designed for Binance Futures. It specializes in **Counter-Trend Scalping** on pumped assets using a sophisticated Martingale strategy enhanced with AI analysis (Grok) and strict risk management.

## 🌟 Key Features

### 1. 🧠 AI-Powered Analysis
- **Grok AI Integration:** Consults xAI's Grok for sentiment analysis on major pumps (>40%).
- **Eagle-Eye Vision:** Uses candlestick pattern recognition (Pin Bars, Engulfing) before entering high-risk steps.

### 2. 🛡️ Advanced Risk Management
- **Smart Martingale:** 15-step recovery system with progressive spacing and time delays.
- **Hard Stop-Loss:** Automatic emergency close if position loss exceeds $55 (configurable).
- **Margin Recycling:** Dynamically frees up margin in prolonged trends to prevent liquidation.
- **Trailing Profit:** Locks in profits when price reverses after a win.

### 3. ⚡ High-Performance Scanning
- **Real-time Pump Detection:** Scans hundreds of pairs for rapid price increases (>20%).
- **Volatility Filters:** Ignores low-volume or blacklisted coins.

## 🛠️ Installation

1.  **Clone the repository**
    ```bash
    git clone https://github.com/yourusername/ai_trader.git
    cd ai_trader
    ```

2.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Setup Configuration**
    Create a `.env` file in the root directory:
    ```env
    BINANCE_API_KEY=your_api_key
    BINANCE_API_SECRET=your_api_secret
    GROK_API_KEY=your_grok_api_key
    ```

4.  **Configure Bot**
    Edit `config.py` to adjust risk settings, leverage, and martingale steps.

## 🚀 Usage

Run the bot in **Testnet Mode** (default) first to verify performance:

```bash
python legendary_scalper.py
```

To switch to **Real Money**:
1.  Open `config.py`
2.  Set `USE_TESTNET = False`
3.  Restart the bot.

## ⚠️ Disclaimer
This software is for educational purposes only. Cryptocurrency trading involves high risk. The authors are not responsible for any financial losses incurred while using this bot. **Use at your own risk.**
