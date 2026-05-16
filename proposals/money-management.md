# Money Management Model

> Designed 2026-05-17. Goal: balance recouping initial capital with compounding gains.
> Avoids the "depleted and tempted to go all-in again" trap.

---

## The Problem with Simple Rules

**"Recoup and run" (lump sum withdrawal):**
$10 → wait for 4x → take $12 → trade $28
- Takes too long to trigger
- One bad run wipes the trading stack back to small
- Creates pressure to deposit more

**"Fixed % on every gain" (e.g. 25/75 always):**
- Never gives you the psychological win of recouping your initial
- Extraction feels slow and abstract

---

## The Hybrid: 3-Phase Model

### Phase 1 — Recoup
**Trigger:** Active until you've banked ≥ initial deposit  
**Rule:** Bank 40% of every gain, trade with 60%  
**Goal:** Get your own money back as fast as possible  
**Why 40%:** Aggressive enough to recoup quickly, leaves enough capital to keep compounding

### Phase 2 — Free-Roll
**Trigger:** Banked amount ≥ initial deposit  
**Rule:** Bank 20% of every gain, trade with 80%  
**Goal:** Compound hard on house money with small consistent extraction  
**Why 20%:** You're at zero personal risk — optimise for growth, not safety

### Phase 3 — Scale
**Trigger:** Trading capital ≥ 3× the Phase 2 starting stack  
**Rule:** Bank 10–15% of every gain, trade with 85–90%  
**Goal:** Maximum compounding, minimal extraction drag  
**Why reduce further:** System is proven, let it run

---

## Example Run Starting at $10

| Event | Trading Capital | Banked (cumulative) | Phase |
|-------|----------------|---------------------|-------|
| Start | $10.00 | $0.00 | 1 |
| +$6 gain | $13.60 | $2.40 | 1 |
| +$10 gain | $19.60 | $6.40 | 1 |
| +$10 gain | $25.60 | **$10.40** ✅ | → 2 |
| +$10 gain | $33.48 | $12.40 | 2 |
| +$20 gain | $49.48 | $16.40 | 2 |
| +$28 gain | $71.88 | $22.00 | 2 |
| 3× hit ($76.80) | $76.80 | ~$23.00 | → 3 |
| +$30 gain | $102.30 | $27.50 | 3 |

Phase 2 entry (trading $25.60) is entirely profit — zero personal money at risk from this point.

---

## Rules for Gain Measurement

"Gain" = increase from the last recorded portfolio high-water mark.

- High-water mark is updated on every poll cycle
- Only extract when portfolio exceeds the previous high-water mark
- Losses don't trigger extraction (no extracting during drawdown)
- Extraction is notional — tracked in DB, transferred manually or via separate wallet logic

---

## Per-Strategy vs Total Portfolio

Two ways to apply this:

**Option A — Total portfolio:** One pool, one phase tracker. Simpler. All strategies
contribute to the same extraction pot.

**Option B — Per-strategy:** Each strategy has its own phase tracker and extraction
counter. Better attribution, more complex. Useful once 3+ strategies are running.

Recommended: start with Option A, migrate to Option B in Phase 3.

---

## Implementation

```sql
CREATE TABLE money_management (
    id             INTEGER PRIMARY KEY,
    phase          INTEGER NOT NULL DEFAULT 1,  -- 1, 2, or 3
    initial_deposit REAL NOT NULL,
    banked_total   REAL NOT NULL DEFAULT 0,
    hwm            REAL NOT NULL,               -- high-water mark
    last_updated   TEXT NOT NULL
);
```

On every daily summary:
1. Compare current portfolio value to `hwm`
2. If above: compute gain, extract per phase %, update `banked_total`, update `hwm`
3. If phase trigger met: advance phase, log event, alert via Telegram
4. Report banked total and current phase in daily summary card

---

## Phase Summary

| Phase | Condition | Bank | Trade | Psychological state |
|-------|-----------|------|-------|---------------------|
| 1 — Recoup | Until banked ≥ initial | 40% | 60% | Recovering investment |
| 2 — Free-roll | Until capital ≥ 3× Phase 2 start | 20% | 80% | Playing with house money |
| 3 — Scale | Ongoing | 10–15% | 85–90% | Proven system, compounding |
