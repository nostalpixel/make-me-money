# Strategy Enhancement Proposals

> Sourced from Codex independent review (2026-05-16).  
> Current strategy: RSI(14) + MACD histogram on BTC/USDT 15m, Bybit spot.  
> Status: **do not implement while a position is open.**

---

## P1 — Exchange-Native SL/TP Orders

**Problem:** SL and take-profit are checked only every 15 minutes by polling. A wick or
flash move can blow past the stop before the bot reacts. If the process dies between polls,
the position has no protection at all.

**Proposal:** Immediately after a BUY is filled, place a native OCO (One-Cancels-Other)
order on Bybit — a limit sell at TP price and a stop-market sell at SL price. The bot poll
then only monitors for position reconciliation, not for risk management.

**Bybit API:** `POST /v5/order/create` with `orderType=Limit` + `stopLoss`/`takeProfit` params,
or two separate conditional orders.

**Impact:** Eliminates the 15-min execution gap. Position is protected even if the bot crashes.

---

## P2 — Higher-Timeframe Trend Filter

**Problem:** The strategy takes trades in both directions (RSI crossovers up or down) without
knowing whether the broader trend supports the entry. This produces a lot of counter-trend
chop trades on 15m.

**Proposal:** Only take a BUY signal when the 1h or 4h trend is also bullish — e.g. price
above the 50-period EMA on the 1h candle, or 1h MACD histogram positive. Require alignment
before entering. SELL signal is unchanged (exit to protect).

**Implementation:** Fetch 1h OHLCV in addition to 15m in `poll_market`, pass to a
`get_trend_filter()` function in `strategy.py`. Gate the BUY branch on `trend == "UP"`.

**Impact:** Reduces number of trades but improves win rate. Codex assessment: "usually
improves win-rate consistency more than tweaking RSI thresholds by a few points."

---

## P3 — ATR-Based Position Sizing

**Problem:** Fixed 50% allocation per trade regardless of volatility or signal strength.
In high-volatility periods the risk per trade is much larger than in calm periods.

**Proposal:** Size each trade based on risk budget rather than fixed percentage.
1. Compute ATR(14) on 15m closes.
2. Set stop distance = 1.5× ATR (instead of fixed 5%).
3. Compute position size as: `risk_usdt / stop_distance_usdt` where `risk_usdt` = 1–2% of portfolio.
4. Cap at 50% of portfolio as a hard ceiling.

**Impact:** Positions scale down in volatile conditions (fewer large losses) and scale up in
calm conditions (more efficient use of capital).

---

## P4 — Spread / Slippage Guard

**Problem:** Market orders are placed blindly with no check on current spread. During low-
liquidity periods (e.g. weekend nights, news events) the spread on BTC/USDT can be
unusually wide and the effective entry price is worse than expected.

**Proposal:** Before placing a market order, fetch the order book (top of book only) and
compute the current spread percentage. If spread > 0.05%, skip the trade and log it.

**Implementation:** `exchange.fetch_order_book('BTC/USDT', limit=1)` → compute
`(ask - bid) / bid * 100`. Add to `place_buy()` as a pre-flight check.

**Impact:** Avoids entering trades at unfair prices. At $10 account size, spread matters more
than at larger sizes.

---

## P5 — Walk-Forward Backtest Validation

**Problem:** RSI(45) + MACD was set empirically. Without out-of-sample validation there is no
way to know if the parameters are robust or just overfit to a specific market period.

**Proposal:** Extend `backtest.py` to run a walk-forward test:
1. Split historical data into 30-day training windows + 7-day out-of-sample windows.
2. Optimize RSI buy/sell thresholds on training window.
3. Test on out-of-sample window with fee simulation (0.1% taker).
4. Report: win rate, Sharpe, max drawdown, parameter stability across windows.

Kill the strategy if performance collapses outside a narrow parameter band — that is the
signature of overfitting.

**Impact:** Provides evidence the edge is real (or kills the bot before it loses more money).

---

## Priority Order

| # | Proposal | Effort | Risk reduction | Recommended next |
|---|----------|--------|----------------|-----------------|
| 1 | Exchange-native SL/TP | Low | High (eliminates poll gap) | ✅ First |
| 2 | Trend filter (1h EMA) | Low | Medium (fewer chop trades) | ✅ Second |
| 3 | ATR position sizing | Medium | Medium (volatility-aware) | Third |
| 4 | Spread guard | Low | Low-medium (minor edge) | Fourth |
| 5 | Walk-forward backtest | Medium | Validation, not live risk | Whenever |
