"""
Bloomberg Terminal - NER Exchange Backend
Run: python app.py
Then open: http://localhost:5000
"""

import json
import time
import math
from datetime import datetime, timedelta
from functools import lru_cache
from flask import Flask, jsonify, request, send_from_directory, Response
import requests as req
import os

# ─── CONFIG ────────────────────────────────────────────────────────────────────
NER_BASE   = "http://150.230.117.88:8082"
API_KEY    = "ner_l7nBYB_pFwRvVPcW2rum-UeI9qrJh2BWekgG__BDeYk"
HEADERS    = {"Content-Type": "application/json", "X-API-Key": API_KEY}
CACHE_TTL  = 10  # seconds for market data cache

app = Flask(__name__, static_folder="static")

# ─── SIMPLE IN-MEMORY CACHE ────────────────────────────────────────────────────
_cache = {}

def cache_get(key):
    if key in _cache:
        val, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return val
    return None

def cache_set(key, val):
    _cache[key] = (val, time.time())

def ner_get(path, params=None):
    """Proxy GET to NER API with caching."""
    cache_key = path + str(params)
    cached = cache_get(cache_key)
    if cached is not None:
        return cached, 200
    try:
        r = req.get(f"{NER_BASE}{path}", headers=HEADERS, params=params, timeout=8)
        data = r.json()
        if r.status_code == 200:
            cache_set(cache_key, data)
        return data, r.status_code
    except Exception as e:
        return {"detail": str(e)}, 503

def ner_post(path, payload):
    """Proxy POST to NER API (no cache)."""
    try:
        r = req.post(f"{NER_BASE}{path}", headers=HEADERS, json=payload, timeout=8)
        return r.json(), r.status_code
    except Exception as e:
        return {"detail": str(e)}, 503

# ─── ROUTES: SERVE FRONTEND ────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

# ─── ROUTES: MARKET DATA ───────────────────────────────────────────────────────
@app.route("/api/securities")
def securities():
    data, status = ner_get("/securities")
    return jsonify(data), status

@app.route("/api/market_price/<ticker>")
def market_price(ticker):
    data, status = ner_get(f"/market_price/{ticker}")
    return jsonify(data), status

@app.route("/api/orderbook")
def orderbook():
    ticker = request.args.get("ticker")
    params = {"ticker": ticker} if ticker else None
    data, status = ner_get("/orderbook", params)
    return jsonify(data), status

@app.route("/api/shareholders")
def shareholders():
    ticker = request.args.get("ticker")
    data, status = ner_get("/shareholders", {"ticker": ticker})
    return jsonify(data), status

# ─── ROUTES: ANALYTICS ─────────────────────────────────────────────────────────
@app.route("/api/analytics/price_history/<ticker>")
def price_history(ticker):
    days = request.args.get("days", 30)
    data, status = ner_get(f"/analytics/price_history/{ticker}", {"days": days})
    return jsonify(data), status

@app.route("/api/analytics/ohlcv/<ticker>")
def ohlcv(ticker):
    days = request.args.get("days", 30)
    data, status = ner_get(f"/analytics/ohlcv/{ticker}", {"days": days})
    return jsonify(data), status

# ─── ROUTES: PORTFOLIO ─────────────────────────────────────────────────────────
@app.route("/api/portfolio")
def portfolio():
    data, status = ner_get("/portfolio")
    return jsonify(data), status

@app.route("/api/funds")
def funds():
    data, status = ner_get("/funds")
    return jsonify(data), status

# ─── ROUTES: ORDERS (TRADING TIER ONLY) ───────────────────────────────────────
@app.route("/api/orders/<order_type>", methods=["POST"])
def place_order(order_type):
    allowed = ["buy_limit", "sell_limit", "buy_market", "sell_market"]
    if order_type not in allowed:
        return jsonify({"detail": "Invalid order type"}), 400
    payload = request.get_json()
    data, status = ner_post(f"/orders/{order_type}", payload)
    return jsonify(data), status

# ─── ROUTES: BACKTESTING ───────────────────────────────────────────────────────
@app.route("/api/backtest", methods=["POST"])
def backtest():
    """
    Simple strategy backtester using price_history data.
    Strategies: SMA_CROSS, RSI, HOLD
    """
    body = request.get_json()
    ticker   = body.get("ticker")
    strategy = body.get("strategy", "SMA_CROSS")
    days     = int(body.get("days", 90))
    short_w  = int(body.get("short_window", 5))
    long_w   = int(body.get("long_window", 20))
    rsi_per  = int(body.get("rsi_period", 14))
    rsi_ob   = float(body.get("rsi_overbought", 70))
    rsi_os   = float(body.get("rsi_oversold", 30))
    init_cash = float(body.get("initial_cash", 10000))
    position_size = float(body.get("position_size", 1.0))  # fraction of cash

    # Fetch history
    data, status = ner_get(f"/analytics/price_history/{ticker}", {"days": days})
    if status != 200:
        return jsonify({"detail": "Could not fetch price history", "raw": data}), 502
    if not data:
        return jsonify({"detail": "No price history available"}), 404

    # Build price series (timestamp sorted)
    data.sort(key=lambda x: x["timestamp"])
    prices = [float(d["price"]) for d in data]
    timestamps = [d["timestamp"] for d in data]
    volumes = [float(d.get("volume", 0)) for d in data]

    # ── Helper: SMA ──
    def sma(arr, w):
        out = [None] * len(arr)
        for i in range(w - 1, len(arr)):
            out[i] = sum(arr[i - w + 1:i + 1]) / w
        return out

    # ── Helper: RSI ──
    def rsi(arr, period):
        out = [None] * len(arr)
        if len(arr) < period + 1:
            return out
        gains, losses = [], []
        for i in range(1, len(arr)):
            d = arr[i] - arr[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        avg_g = sum(gains[:period]) / period
        avg_l = sum(losses[:period]) / period
        for i in range(period, len(arr)):
            if avg_l == 0:
                out[i] = 100
            else:
                rs = avg_g / avg_l
                out[i] = 100 - 100 / (1 + rs)
            if i < len(arr) - 1:
                g = gains[i] if i < len(gains) else 0
                l = losses[i] if i < len(losses) else 0
                avg_g = (avg_g * (period - 1) + g) / period
                avg_l = (avg_l * (period - 1) + l) / period
        return out

    # ── Generate signals ──
    signals = [None] * len(prices)
    indicators = {}

    if strategy == "SMA_CROSS":
        s_sma = sma(prices, short_w)
        l_sma = sma(prices, long_w)
        indicators["short_sma"] = s_sma
        indicators["long_sma"] = l_sma
        for i in range(1, len(prices)):
            if s_sma[i] is None or l_sma[i] is None:
                continue
            if s_sma[i] > l_sma[i] and (s_sma[i-1] is None or l_sma[i-1] is None or s_sma[i-1] <= l_sma[i-1]):
                signals[i] = "BUY"
            elif s_sma[i] < l_sma[i] and (s_sma[i-1] is None or l_sma[i-1] is None or s_sma[i-1] >= l_sma[i-1]):
                signals[i] = "SELL"

    elif strategy == "RSI":
        rsi_vals = rsi(prices, rsi_per)
        indicators["rsi"] = rsi_vals
        for i in range(1, len(prices)):
            if rsi_vals[i] is None or rsi_vals[i-1] is None:
                continue
            if rsi_vals[i-1] < rsi_os and rsi_vals[i] >= rsi_os:
                signals[i] = "BUY"
            elif rsi_vals[i-1] > rsi_ob and rsi_vals[i] <= rsi_ob:
                signals[i] = "SELL"

    elif strategy == "HOLD":
        signals[0] = "BUY"

    # ── Simulate portfolio ──
    cash = init_cash
    shares = 0.0
    trades = []
    equity_curve = []
    commission = 0.005  # 0.5%

    for i, price in enumerate(prices):
        sig = signals[i]
        if sig == "BUY" and cash > 0:
            invest = cash * position_size
            qty = invest / price
            cost = invest * (1 + commission)
            if cost > cash:
                qty = (cash / price) / (1 + commission)
                cost = cash
            shares += qty
            cash -= cost
            trades.append({"i": i, "type": "BUY", "price": price, "qty": round(qty, 4), "ts": timestamps[i]})
        elif sig == "SELL" and shares > 0:
            proceeds = shares * price * (1 - commission)
            cash += proceeds
            trades.append({"i": i, "type": "SELL", "price": price, "qty": round(shares, 4), "ts": timestamps[i]})
            shares = 0

        equity_curve.append({"ts": timestamps[i], "equity": round(cash + shares * price, 4), "price": price})

    # Close any open position at last price
    final_price = prices[-1]
    if shares > 0:
        cash += shares * final_price * (1 - commission)
        shares = 0

    # ── Stats ──
    final_equity = cash
    total_return = (final_equity - init_cash) / init_cash * 100
    bh_return = (prices[-1] - prices[0]) / prices[0] * 100

    equities = [e["equity"] for e in equity_curve]
    peak = equities[0]
    max_dd = 0
    for e in equities:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Sharpe (simplified daily returns)
    daily_rets = []
    for i in range(1, len(equities)):
        if equities[i-1] != 0:
            daily_rets.append((equities[i] - equities[i-1]) / equities[i-1])
    sharpe = None
    if len(daily_rets) > 1:
        mean_r = sum(daily_rets) / len(daily_rets)
        var_r = sum((r - mean_r)**2 for r in daily_rets) / len(daily_rets)
        std_r = math.sqrt(var_r) if var_r > 0 else 0
        sharpe = round((mean_r / std_r) * math.sqrt(252), 3) if std_r > 0 else None

    win_trades = [t for i, t in enumerate(trades) if t["type"] == "SELL"]
    buy_trades  = [t for t in trades if t["type"] == "BUY"]
    # match buy/sell pairs for win rate
    pnl_per_trade = []
    bi = 0
    for t in trades:
        if t["type"] == "SELL" and bi < len(buy_trades):
            pnl_per_trade.append(t["price"] - buy_trades[bi]["price"])
            bi += 1
    wins = sum(1 for p in pnl_per_trade if p > 0)
    win_rate = wins / len(pnl_per_trade) * 100 if pnl_per_trade else None

    return jsonify({
        "ticker": ticker,
        "strategy": strategy,
        "days": days,
        "initial_cash": init_cash,
        "final_equity": round(final_equity, 4),
        "total_return_pct": round(total_return, 3),
        "buy_hold_return_pct": round(bh_return, 3),
        "max_drawdown_pct": round(max_dd, 3),
        "sharpe_ratio": sharpe,
        "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
        "num_trades": len(trades),
        "trades": trades[-50:],  # last 50
        "equity_curve": equity_curve[-500:],  # last 500 points
        "price_series": [{"ts": timestamps[i], "price": prices[i]} for i in range(len(prices))][-500:],
        "indicators": {
            k: [{"ts": timestamps[i], "val": v} for i, v in enumerate(vals) if v is not None]
            for k, vals in indicators.items()
        }
    })

# ─── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("╔══════════════════════════════════════════╗")
    print("║   BLOOMBERG TERMINAL — NER Exchange      ║")
    print("║   http://localhost:5000                  ║")
    print("╚══════════════════════════════════════════╝")
    app.run(debug=False, port=5000, host="0.0.0.0")
