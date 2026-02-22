# BLOOMBERG TERMINAL — NER Exchange

Classic Bloomberg-style terminal for the NER Exchange (DemocracyCraft).

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Then open: **http://localhost:5000**

## Architecture

```
app.py          ← Flask backend — proxies all NER API calls
index.html      ← Frontend — served by Flask at /
```

The backend sits between your browser and the NER API. This handles:
- CORS (browser can't call the NER API directly)
- In-memory caching (10s TTL) to respect rate limits
- Backtest computation server-side

## Views (F1–F5)

| Key | View | Description |
|-----|------|-------------|
| F1  | MARKETS | All securities, prices, spreads, orderbook summary. Auto-refreshes every 30s. |
| F2  | TICKER  | Deep-dive: OHLCV chart, orderbook depth, top shareholders. Click any row in F1 to jump here. |
| F3  | PORTFOLIO | Your holdings, cash balance, unrealized P&L, doughnut allocation chart. |
| F4  | ORDERS | Live market context + order simulator (preview commission costs). Live execution requires Trading Tier key. |
| F5  | BACKTEST | Strategy backtester using historical price data. |

## Backtesting Strategies

### SMA Crossover
- BUY when short SMA crosses above long SMA
- SELL when short SMA crosses below long SMA
- Parameters: short window (default 5), long window (default 20)

### RSI Mean Reversion
- BUY when RSI crosses back above oversold threshold
- SELL when RSI crosses back below overbought threshold
- Parameters: period (14), overbought (70), oversold (30)

### Buy & Hold
- Simple benchmark — buy at first data point, hold.

## Metrics Explained

- **Total Return** — Strategy return vs initial cash
- **B&H Return** — What buy-and-hold would have returned on same ticker
- **Alpha** — Strategy outperformance vs buy-and-hold
- **Max Drawdown** — Worst peak-to-trough decline
- **Sharpe Ratio** — Risk-adjusted return (annualized, simplified)
- **Win Rate** — % of closed trades that were profitable

## API Key

Your Analytics-tier key is configured in `app.py`. It gives full read access:
- `/securities`, `/orderbook`, `/shareholders`
- `/market_price/{ticker}`
- `/analytics/price_history/{ticker}`, `/analytics/ohlcv/{ticker}`
- `/portfolio`, `/funds`

Trading endpoints require upgrading to Trading Tier via NER staff.

## Rate Limiting

The backend caches market data for 10 seconds. The frontend refreshes every 30 seconds.
This keeps you well under the 60 req/min per-key limit.
