# Masterclass Knowledge Base

Source: "Spartan Trades Masterclass Series," provided by TradeLikeGates (uploaded
by the user 2026-08-17). Educational day-trading course, 6 series + a video list.
**Series 1, 2, 3, 4, and 6 have been read and are summarized below. Series 5
(volatility, options contract specs, bid/ask spread, open interest, scaling
in/out, profit-taking methods) has not been provided yet — fold it in here
when it is.**

## Purpose and boundary

This is a reference document, not an auto-pilot. Per the same governance
principle established for `src/logging/trade_journal.py`: nothing in this
codebase gets rewritten because a guide said so. Every gap identified below
between what the masterclass recommends and what `src/strategy/`,
`src/risk/`, and `src/position_manager/` actually do is presented as a
**question for the user**, not a change already made. If a change is wanted,
it happens the same way every other change to this system has happened all
project — asked for, explicitly, then implemented, tested, and documented.

The agent should read this file at the start of a cycle (or when reasoning
about a candidate) as *context* — the vocabulary and reasoning framework
below is useful for narrating *why* a setup looks good or bad in terms this
system's own decision log already uses (breakout, consolidation, S/R,
trendline, RSI/MACD/EMA/VWAP, multi-signal confirmation) — not as a second,
competing rulebook that silently overrides `RiskManager` or
`MomentumBreakoutStrategy`.

---

## 1. Core philosophy (Series 1, 3)

- **Trade to learn first, profit second**, especially in the first 3-5
  months on one strategy/account size before scaling up or changing
  strategy.
- **Never risk more than 10% of total account value on one trade; never
  lose more than 10% of that 10%** — i.e. cap the loss on any single trade
  at **1% of total account value**. Framed as: you can be wrong 100 times
  in a row before blowing the account.
- **One setup, focused.** Pick a specific, well-defined edge (e.g. "gap-up
  continuation" or "ascending triangle breakout with confirmed volume") and
  trade *only* that, repeatedly, until the data says it isn't working.
- **No daily profit target.** Forcing a trade to hit a self-imposed daily
  number is exactly how a bad setup gets taken. Some days have zero
  qualifying setups — that's fine and expected.
- **A trading plan has five parts, every time**: Entry, Exit, Position Size
  (Risk), Stop Loss, Profit target. If it can't fit on the back of an
  envelope, it's too complicated.
- **Discipline → consistency → profitability**, in that order. Rules
  (paraphrased, the ones with real teeth): trade with a plan; take profit
  when offered (scale out, don't get greedy); cut losses early; never hold
  a planned day trade overnight; don't enter on someone else's call without
  your own independent read; don't trade the first 5-10 minutes after open;
  don't get emotional — wins and losses are both just journal data points.
- **Trading journal, every closed trade**: ticker, return %, duration,
  entry/exit price, size, why you entered/exited, date, $ value, running
  P&L. Review weekly, not daily — look for patterns (holding losers too
  long, one setup consistently winning, one ticker consistently losing).

**Cross-reference — already built, matches:**
`src/logging/trade_journal.py` already records exactly this shape per
closed trade (thesis, entry/exit, duration via `hold_minutes`, realized
P&L, a deterministic "lesson"). `RiskManager` already enforces a hard
position-size and daily-loss cap. The evaluator's step-by-step
HOLD/EXIT/TARGET_EXIT/STOP_EXIT logging is the "write down every trade and
why" principle in code form.

**Gap — not currently enforced:**
- The **1%-of-account max loss per trade** framed as *(10% position sizing)
  × (10% stop within that position)* is not how `MAX_POSITION_SIZE_USD` /
  stop-loss are currently derived — today they're flat dollar values set by
  the user ($97 position cap, per-position stop from
  `MomentumBreakoutConfig.stop_loss_pct` = 50% of premium). The masterclass
  math would imply a *much* tighter per-trade stop as a fraction of premium
  than 50%. Worth a conscious decision, not a silent switch.
- **"Never hold a planned day trade overnight"** — nothing in this codebase
  currently forces a close-by-end-of-day for a position that hasn't hit
  target/stop. `PositionEvaluator` only forces a close inside
  `expiration_buffer_minutes` of the contract's *expiration*, which for a
  weekly option is not the same as "today." A position opened Monday on a
  Friday-expiry contract can currently be held Tuesday, Wednesday, Thursday
  per the existing logic — that's a real gap versus this masterclass's
  explicit rule if the intent is pure day trading.

---

## 2. Reading the market (Series 1-4)

- **Support/resistance**: price zones (not exact lines) where a stock
  historically reverses or stalls. Stronger with more touches, stronger on
  higher timeframes, stronger after a steep approach. "Old resistance
  becomes new support" and vice versa once broken. Round numbers ($50,
  $100...) and moving averages (50/200 EMA) act as S/R too, not just
  horizontal/diagonal lines.
- **Candlestick anatomy**: body = open/close, wicks = high/low reached
  within the period. Reversal candles worth knowing: shooting star (top of
  a run, long upper wick, exhaustion), hammer (bottom of a downtrend, long
  lower wick, exhaustion), bullish engulfing (2-candle, full reversal of
  control). Doji = indecision, weak signal alone.
- **Volume confirms moves.** A breakout on rising volume is more likely
  real; a breakout on thin volume is more likely a fake-out. Relative
  volume (current vs. historical average) is the "how in-play is this
  stock right now" gauge — the masterclass explicitly ties this to why
  algorithmic/human participation matters for pattern reliability.
- **Consolidation** = sideways chop in a defined range; avoid trading
  *inside* it, wait for the break of the range.
- **Gaps**: price jumps between one session's close and the next session's
  open, usually news/earnings-driven. Gaps tend to either continue
  (momentum) or "fill" (price returns to pre-gap level) because there's no
  S/R inside the gap void. Two playbooks given: gap-up continuation (wait
  20-50 min after open, enter on break of high-of-day if price holds above
  the 9 EMA) and gap-fill-then-reclaim (wait for price to retest the
  gapped-through level as new support/resistance).
- **Timeframe discipline**: start analysis on the largest relevant
  timeframe (weekly → daily → 5-min) and work down; a day trader's actual
  entries come off the 5-minute chart, informed by the daily chart's S/R.
  The 1-minute chart is explicitly called out as noisy/unreliable for a
  newer trader.
- **Patterns** (continuation: flags, pennants, wedges, ascending/descending
  triangles, cup-and-handle; reversal: double top/bottom, head & shoulders,
  inverted head & shoulders): all require a **confirmed break with rising
  volume**, not just the shape forming. A close back inside the pattern
  after a break = failed breakout = cut the position.
- **Multi-signal confirmation, never one indicator alone**: RSI, MACD/RSI
  tandem, EMA crossover (9/21 for intraday, 50/200 "golden cross" for
  swing), VWAP (most reliable ~30-60 min into the session), trendline
  breaks. RSI >70 = overbought, <30 = oversold, used loosely and always
  subordinate to fundamentals/news. The stronger the setup, the more of
  these line up in the same direction at once.

**Cross-reference — already built, matches almost exactly:**
`src/market/indicators.py` / `src/strategy/evidence.py` already compute
RSI, RSI-previous, MACD histogram (+ previous), EMA fast/slow,
higher-highs/lower-highs structure, breakout-continuation, failed-breakout,
and volume ratio, and `evaluate_momentum()` already requires *multiple*
corroborating signals (`WEAKENING_THRESHOLD = 3`, `REVERSING_THRESHOLD =
5`) before calling a move weakening/reversing — this is precisely the "never
rely on one indicator" rule already encoded, independently arrived at.
`MomentumBreakoutStrategy` already requires a confirmed
`breakout_continuation` **and** a `STRENGTHENING` read before treating
anything as a candidate, matching "wait for the break with volume, not the
setup forming."

**Gap — not currently used:**
- **VWAP** is not implemented anywhere in this codebase (`indicators.py`
  has no VWAP function, `MomentumEvidence` has no VWAP field). The
  masterclass treats it as one of the core intraday reference lines,
  especially valuable ~30-60 min into the session.
- **Multi-timeframe analysis** (weekly → daily → 5-min) is not how this
  system scans — `HoodMarketDataProvider`'s lookback is a single rolling
  window (`history_lookback_minutes`, default 180) at one interval. There's
  no cross-timeframe check (e.g. "is the daily trend also up before taking
  a 5-min breakout").

---

## 3. Time of day (Series 3)

- **Best trading windows**: first 1-2 hours after open (9:30-11:30 ET) and
  the last hour (3:00-4:00 ET). These have the volatility and volume that
  actually move option premiums.
- **Avoid lunch** (roughly 11:30 ET-2:30 ET): low volume, choppy,
  directionless — "the lunch time lull."
- **Avoid the first 5-10 minutes of the open** unless the direction is
  unambiguous — that window is overnight-position unwind + new sentiment
  settling, genuinely chaotic.
- **Mental fatigue is real** — trading fewer, higher-quality hours beats
  sitting at the screen all day; willpower/discipline visibly erodes over
  a long session.

**Cross-reference — already built, partial match:**
`ENTRY_CUTOFF_TIME=15:30` already stops *new* entries late in the day, and
the scanning cron self-gates to 9:20am-4:00pm ET. `MomentumBreakoutStrategy`
has no rule against entering in the first 5-10 minutes, and no lunch-window
exclusion — the strategy currently scans uniformly across the whole
9:20-4:00 window with no time-of-day weighting or blackout period.

**Gap — worth a decision:**
- Add an explicit **first-10-minutes** and/or **lunch-chop** blackout
  window to `RiskManager` or the scanner? This is a real, concrete,
  low-risk rule this masterclass makes a strong case for, and it maps
  cleanly onto a `check_time_of_day` style gate similar to the existing
  cutoff-time check.

---

## 4. Options-specific (Series 6; Series 5 pending)

- **Weekly options only for day trading** — anything with >2 weeks to
  expiration isn't in scope for this style. If holding overnight is the
  intent, the masterclass says use spreads instead (not covered — this
  system trades naked long calls only, matching the "day trade weeklies"
  half of that split, not the "hold longer, use spreads" half).
- **Day trade means bought and sold same day, always** — theta decay on a
  short-dated option is the explicit reason given for never holding
  overnight on a directional single-leg position.
- **Contract selection golden rules**:
  - Mon/Tue/Wed → buy that Friday's expiration. Thu/Fri → buy *next* week's
    expiration (extra buffer against theta into the weekend).
  - Target **delta 0.40-0.60** (roughly 1-2 strikes ITM to 1 strike OTM) —
    below that, premium doesn't move enough with the stock; above that,
    volatility/cost gets too punishing if wrong.
  - Open interest **≥ 1,000**, and a tight bid/ask spread.
- **"Moving set-ups" only** — the five patterns worth trading naked
  directional options against: gap plays, all-time-high breaks, larger-
  timeframe pattern breakouts, news plays, range breaks. Explicitly *not*
  chop/consolidation — theta burns you while a contract just sits.
- **Exit discipline, numeric**: stop loss around 8-10% of the position;
  take profit around 17-20% (a ~2:1 reward:risk ratio, meaning you can be
  wrong twice for every one win and still break even). Once favorable, move
  the stop to breakeven — "risk-free trade."
- **Scaling in** on a dip instead of full size up front, to avoid getting
  stopped out right before a move goes your way; have a defined re-entry
  plan rather than fearing a ticker after one stop-out.
- **Stock selection for options specifically**: the masterclass explicitly
  recommends underlyings in the **$50-500 range** — below that, strikes are
  too widely spaced and lower-cap stocks don't have enough ATR/delta
  sensitivity to move the premium meaningfully. It explicitly, repeatedly
  warns **against penny stocks (anything under $10)**: illiquid, prone to
  pump-and-dump, no reliable chart "rhythm," hard to do any technical
  analysis on.
- **Never trade into earnings** — "whisper numbers" known to institutional
  analysts make pre-earnings direction close to a coin flip; better to
  trade the gap the *next* day using the gap-continuation playbook already
  covered.
- **Compounding**: focus on % account growth per period rather than a fixed
  dollar target — the same $100 gain means something very different on a
  $500 account vs. a $50,000 one, so a fixed daily $ goal is the wrong unit.

**Cross-reference — already built, matches:**
`MomentumBreakoutStrategy` already restricts to a `min/max_days_to_expiration`
window (7-45 days — narrower framing than "weekly" but same spirit of not
buying far-dated LEAPS) and already requires liquidity (`min_volume`,
`min_open_interest`) and spread checks (`max_spread_pct`) before a candidate
qualifies — directly matching "tight bid/ask + OI floor." The "moving
set-ups only" list overlaps heavily with what `breakout_continuation` +
`STRENGTHENING` already require.

**Gap — the important one, needs an explicit decision:**
This is the direct, real conflict with the recent scan-universe change:

> **The masterclass explicitly says avoid penny stocks (<$10) and prefer
> $50-500 underlyings. The current `SCAN_UNIVERSE` (NIO ~$4.6, MARA ~$9.3,
> SOFI ~$18, SOUN ~$7, PLUG ~$2.3) is mostly *inside the range this guide
> calls a penny stock* — three of five tickers are literally under $10.**

That swap was made for a documented, real reason: at the old universe
(SPY/QQQ/AAPL/MSFT/NVDA), `MomentumBreakoutStrategy`'s fixed 1-contract,
ATM sizing made every candidate unaffordable at `MAX_POSITION_SIZE_USD=97`
— see the .env comment from 2026-08-17. The masterclass's stock-selection
philosophy and this account's dollar constraint are pulling in genuinely
opposite directions, and there is no code fix that satisfies both at once
without either (a) funding the account well past $100, (b) building
account-size-aware sizing logic that could afford a $50-500 stock's option
at less than 1 full contract (not possible — options are integer
contracts), or (c) accepting the tradeoff already made and treating these
tickers' *higher IV* as the deliberate substitute for the masterclass's
preferred "big stock, smooth chart, big ATR" liquidity profile — cheaper
absolute price, similar-or-larger relative moves, same real premium
sensitivity, just noisier/choppier charts than the guide's ideal.

This isn't something to silently resolve either direction — flagging it
plainly is the point of this document existing.

- **Contract selection by delta (0.40-0.60)** is not implemented — the
  current strategy always picks the strike **closest to spot** (ATM,
  `_select_contract` in `momentum_breakout.py`), which is usually close to
  0.50 delta anyway for a call, but it's coincidental, not a deliberate
  delta-band check, and there's no `get_option_instruments`/pricing call
  that reads delta at all currently.
- **Numeric exit bands (~10% stop / ~20% target as % of premium)**:
  `MomentumBreakoutConfig` already uses `profit_target_pct=0.50` and
  `stop_loss_pct=0.50` (50%/50%) by default — both symmetric and much
  wider than the masterclass's ~10%/~20% (2:1, asymmetric) framing. Worth
  a conscious comparison, not an assumption either number is "right."
- **Same-day-only exit enforcement**: same gap noted in section 1 — nothing
  currently forces a position closed same-day regardless of target/stop.

---

## 5. What this file is for going forward

- Read it for vocabulary and reasoning when narrating *why* a candidate
  does or doesn't look like a real setup — it's the same language this
  system's own decision log already speaks (breakout, consolidation,
  volume confirmation, multi-signal confluence).
- Treat every "Gap" callout above as a menu of **possible, explicit** asks
  the user could make, not pending work. None of them get implemented
  without being asked for.
- Update this file when Series 5 arrives (volatility, contract specs, bid/
  ask spread mechanics, open interest, scaling in/out in more depth, and
  the five profit-taking sub-strategies: profit-target, whole-number,
  HOD/LOD, VWAP-band, EMA-cross, trendline-break trading).
