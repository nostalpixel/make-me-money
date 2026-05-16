# Trading Philosophy

> Established 2026-05-17. This is the north star for all strategy and risk decisions.

---

## Core Belief

**BTC is a long-term hold.** A crash to zero is not a realistic scenario worth designing around.
Dips are opportunities to accumulate, not reasons to exit.

This changes the entire risk model compared to a neutral trading bot.

---

## Capital Model

Two pools, always:

| Pool | Purpose | Target allocation |
|------|---------|-------------------|
| **BTC Hold** | Long-term position, rides dips | 50–70% of portfolio |
| **USDT Opportunity Fund** | Active trading capital | 30–50% of portfolio |

The bot only trades within the Opportunity Fund. The Hold pool is never auto-sold.

If the Opportunity Fund drops below a floor (e.g. $20 on a $100 account), the bot alerts
and pauses entries — it doesn't chase trades with the last available capital.
Top-ups to restore the Opportunity Fund are expected and healthy.

---

## Stop-Loss Philosophy

**No hard auto-exit stop-loss.**

Instead, graduated alert thresholds on open positions:

| Drawdown | Action |
|----------|--------|
| -5% | Warning alert: "Position down 5%, watching" |
| -10% | Alert: "Liquidity attention needed — down 10%, new entries paused" |
| -15% | Strong alert: "Significant drawdown — manual review required" |
| -20%+ | Escalating alerts, stay paused until human sends /resume |

Bot never auto-sells BTC. Human decides when to exit a losing position.

**Rationale:** Holding BTC through a -20% dip is not a failure. Selling at -5% and missing
the recovery is. The bot harvests gains; it doesn't panic on losses.

---

## Take-Profit Philosophy

TP still fires automatically. Asymmetric design:

- **Let losses run** (you hold BTC anyway — opportunity cost, not cash loss)
- **Cut winners at target** (lock profit, restore USDT fund, reload)

Current TP: +8%. Under review — may adjust upward (to +12–15%) given long-term bias,
since a small TP causes many round-trips that bleed fees.

---

## Seasonality Context

Historical BTC pattern (not guaranteed, but useful context):
- **Q1-Q2:** Accumulation / trend establishment
- **Q3 (July–August):** Historically strong — often local high
- **Q4:** Often correction / consolidation before next cycle

**Implication for the bot:**
- More aggressive TP into July–August strength (lock profits before seasonal peak)
- More conservative entries in September (don't chase the top)
- This is not hardcoded — it's a human judgment call informed by the seasonal signal

---

## Top-Up Strategy

Top-ups are a planned feature, not a failure:
- When Opportunity Fund depletes from trading losses, top up to restore trading capability
- Record each top-up in DB so total invested capital is tracked accurately
- Money management phases (from `money-management.md`) are based on profit relative to
  **total invested**, not just initial deposit

---

## What the Bot Is For

The bot is a **profit harvester on top of a long-term BTC position.**

It is not:
- A market timing system
- A system designed to "beat" BTC
- An exit mechanism for the BTC holding

It is:
- A disciplined entry/exit system for the Opportunity Fund
- A tool to compound USDT gains back into position
- An alert system for significant market events
