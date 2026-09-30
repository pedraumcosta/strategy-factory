# Research — DonchianBreakout17 (S1)

Hypothesis: long-only 10/5 Donchian channel breakout, 17 USDT pairs, daily bars,
parameters fixed a priori. Toy method-validation run #2 (M5 acceptance); the point
is the pipeline, not the strategy.

## Sources

### Local shelf (`/home/pedraum/Dropbox/Work/Practices/TechTrading/Library`)

1. **Brock, Lakonishok & LeBaron — "Simple Technical Trading Rules and the
   Stochastic Properties of Stock Returns"** (Journal of Finance 47(5), 1992) —
   `Library/Technical Analysis/William Brock, Josef Lakonishok, Blake LeBaron - Simple
   Technical Trading Rules and the Stochastic Properties of Stock Returns.pdf`
   *(opened, pp. 1–4 verified)*. The canonical academic test of exactly this
   strategy class: "trading range break" (buy when price exceeds a prior high —
   the Donchian entry) plus moving-average rules, DJIA 1897–1986, with bootstrap
   inference against random walk, AR(1), GARCH-M, and EGARCH nulls. Findings:
   buy signals consistently generate higher and less volatile subsequent returns
   than sell signals; results are not consistent with the null models. The paper
   also explicitly flags data-snooping risk (Leamer 1978, Merton 1987) and
   mitigates it by testing only simple, long-established rules — the same
   discipline this card attempts with fixed a-priori parameters. This is the
   strongest evidence on the shelf that the *premise* (post-breakout drift) is a
   real statistical phenomenon, at least historically in equities.

2. **Kaufman — Trading Systems and Methods, 6th ed. (2019)** —
   `Library/Systematic Trading/Perry J. Kaufman - Trading Systems and Methods (Wiley
   Trading) (2019, Wiley) - libgen.li.pdf` *(not opened; cited from knowledge of
   the work)*. Documents Donchian's original 4-week rule (~20-day channel) and
   the N-day breakout as the archetypal trend system; characterizes the payoff
   profile exactly as the card does — low win rate, few large wins, long flat/
   losing whipsaw stretches — and shows breakout systems are among the more
   robust to parameter choice (broad plateaus, not sharp optima).

3. **Weissman — Mechanical Trading Systems (2005)** —
   `Library/Systematic Trading/Mechanical Trading Systems Pairing Trader Psychology
   with Technical Analysis - RICHARD L. WEISSMAN.pdf` *(not opened; from
   knowledge of the work)*. Backtests channel-breakout trend systems across
   futures/FX; emphasizes the psychological cost of the 30–45% win rate and
   multi-month drawdowns in non-trending regimes — the card's kill-condition #3.

4. **Davey — Building Winning Algorithmic Trading Systems (2014)** —
   `Library/Systematic Trading/Building Winning Algorithmic Trading Systems... Kevin
   J. Davey (z-lib.org).pdf` *(not opened; from knowledge of the work)*.
   Process reference, not a Donchian source: insists on realistic
   commission+slippage in every backtest, out-of-sample incubation, and Monte
   Carlo on trade sequences — effectively this factory's screen stages in book
   form.

5. **Halls-Moore — Successful Algorithmic Trading (2015)** —
   `Library/Systematic Trading/Michael Halls Moore - Successful Algorithmic Trading
   (2015).pdf` *(not opened; from knowledge of the work)*. Has an explicit
   transaction-cost chapter (commission, fees, slippage, market impact) and
   treats a cost-free backtest as invalid by construction.

6. **"(Fx) Technical Trading Strategies Returns Risk And Size"** —
   `Library/Technical Analysis/(Fx)Technical Trading Strategies Returns Risk And
   Size.pdf` *(not opened)*. Filed as adjacent evidence that simple technical
   rules in liquid FX show modest, size-sensitive returns; not relied on for any
   claim here.

### Web

7. **Han, Kang & Ryu — "Time-Series and Cross-Sectional Momentum in the
   Cryptocurrency Market: A Comprehensive Analysis under Realistic Assumptions"**
   ([SSRN 4675565](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565)).
   Most relevant academic source found: strong evidence for *time-series*
   momentum in crypto (the card's edge class), weak for cross-sectional — which
   matches the card's `cross_sectional: false` choice. Critically: under
   realistic assumptions many momentum portfolios with statistically significant
   gross returns earn **insignificant net profits** once transaction costs and
   daily price fluctuation are accounted for.

8. **Zarattini, Pagani & Barbon — "Catching Crypto Trends: A Tactical Approach
   for Bitcoin and Altcoins"**
   ([SSRN 5209907](https://papers.ssrn.com/sol3/Delivery.cfm/5209907.pdf?abstractid=5209907&mirid=1)).
   EMA-combination trend signals on the top-20 liquid coins; reports
   **net-of-fees** Sharpe > 1.5 and ~10.8% annualized alpha vs BTC. Supports the
   premise that daily-timeframe crypto trend following can survive costs, though
   with a more sophisticated signal than a raw 10/5 channel.

9. **Coinquant — Donchian breakout crypto backtests**
   ([Donchian vs Keltner](https://www.coinquant.ai/blog/donchian-channel-breakout-on-crypto-backtest-vs-keltner),
   [BTC 30m backtest](https://www.coinquant.ai/strategies/btc-donchian-channel-30m-backtest)).
   Practitioner-grade, not academic: BTC daily Donchian 2022–2026 reported
   +36.5% with 36% win rate and 38.5% max drawdown, profitability dependent on a
   few large trends — the exact concentration shape anti-pattern #4 warns about.

10. **PyQuantLab — Donchian breakout walkthrough**
    ([Medium](https://pyquantlab.medium.com/a-donchian-channel-breakout-strategy-a-simple-trend-following-approach-18b7b74c4358))
    and **TradingCode.net Pine implementation**
    ([tradingcode.net](https://www.tradingcode.net/tradingview/donchian-channel-breakout/)).
    Tutorial-grade confirmations of the mechanics and typical 20/10 or 20/55
    parameterizations; inspiration-only.

11. **Turtle Traders provenance** (Donchian 1960s 4-week rule; Turtle System 1:
    20-day entry / 10-day exit; System 2: 55/20) — *reasoned from well-known
    trading history, not sourced to a specific shelf file*; Kaufman (source 2)
    documents it.

The premise itself — post-high drift from herding and slow information
diffusion — is consistent with BLL (source 1) historically and Han et al.
(source 7) in crypto specifically. The "structural upward drift makes long-only
sensible" claim is **reasoned, not sourced**: it is survivorship-tinged (the 17
pairs are today's survivors of the lab config) and holds only across the sample
bulls.

## Cost model of the sources

| # | Source | Models costs? | How |
|---|---|---|---|
| 1 | Brock, Lakonishok & LeBaron 1992 | **No** | Tests forecastability, not implementable profit; returns are pre-cost, and the authors themselves caution that transaction costs must be weighed before trading the rules. Inspires the premise; justifies nothing about net edge. |
| 2 | Kaufman 2019 | Partially | Discusses commission/slippage as system-design inputs, but many illustrative backtests are cost-light. Class reference, not a net-edge source. *(From knowledge of the work.)* |
| 3 | Weissman 2005 | Partially | Deducts fixed per-round-turn slippage+commission in his futures backtests; crude flat deduction, nothing crypto-fee-shaped. *(From knowledge of the work.)* |
| 4 | Davey 2014 | **Yes (methodologically)** | Entire thesis: no backtest counts without realistic commission+slippage and incubation. No crypto numbers, but the right doctrine. *(From knowledge of the work.)* |
| 5 | Halls-Moore 2015 | **Yes (methodologically)** | Dedicated transaction-cost-modeling chapter (fees, slippage, impact). *(From knowledge of the work.)* |
| 6 | Fx returns/risk/size paper | Unverified (not opened) | Cannot be used to justify anything until opened. |
| 7 | Han, Kang & Ryu | **Yes, centrally** | The paper's whole point: realistic crypto fee/cost assumptions turn many significant gross momentum returns into insignificant net returns. The single most load-bearing cost source for this hypothesis. |
| 8 | Zarattini et al. | **Yes** | Reports net-of-fees performance on liquid top-20 coins. |
| 9 | Coinquant backtests | **Yes, thin** | Flat commission per trade (0.1% in one backtest, 0.045% in another); no slippage/impact model. Breakouts buy strength, so flat-fee-only models understate true cost — their own material concedes slippage works against breakout fills. |
| 10 | PyQuantLab / TradingCode | Mostly no / token | Tutorial commission settings at best; inspiration only. |

Net: the two sources that model crypto costs seriously (7, 8) point in opposite
directions — costs kill many naive momentum implementations (7), yet a
liquid-universe daily trend system can survive net of fees (8). The card's own
kill-condition #1 (0.156% round-trip recurring ~50×/year/slot, worse on HBAR/
ALGO/ZEC) is the correct frame and must be carried into the screen as an
explicit all-in cost haircut on the 1.0% gross edge, with a thin-alt slippage
multiplier — a flat maker/taker fee is not enough for a strategy that by
construction buys into strength.

## Anti-patterns check

1. **Lookahead.** Low risk on paper: `shift_periods = 1` computes channels on
   prior completed bars, which kills the classic bug (a channel including the
   current bar's high can never be broken by its own close, and its sibling —
   comparing today's close to a channel containing today — looks ahead).
   Residual implementation risks the screen must verify: (a) fills must occur
   at the **next bar's open**, not the signal bar's close; (b) the -10% stop on
   daily bars must be filled pessimistically — a gap through the stop fills at
   the open, not at -10% (backtester defaults are often optimistic here); (c) no
   full-series normalization anywhere (none is specified — keep it that way).

2. **In-sample-only evidence.** Moderate risk, currently well handled: the
   card's estimates come from lab priors, not from a backtest of this strategy,
   so nothing has been fitted yet. The risk materializes at the screen/backtest
   stage: one ~8-year chronological run with no control arm is exactly the
   failure mode. The screen needs at least a holdout split fixed before running,
   plus a control arm (e.g., BTC buy-and-hold and/or random-entry-same-exit
   baseline) — long-only crypto over 2017–2025 makes *everything* look like
   edge.

3. **Tuning on the evaluation data.** Low risk as written: 10/5, -10% stop,
   daily, long-only are all fixed a priori and the card forbids later tuning.
   One honest caveat to record: this is the *same idea resubmitted* after run
   #1 died at the noise-floor screen, with the universe enlarged 5→17. That is
   a mild forking path. It is defensible here because the resize targets
   statistical power (trade count), not performance, and was decided before
   seeing any backtest of either run — but the pipeline should log resubmissions
   so this pattern can't silently become "retry until a screen passes."

4. **Return concentration.** **HIGH risk — this is the strategy's most likely
   death.** Long-only trend on 17 heavily BTC-correlated pairs will fire
   clustered breakouts and harvest essentially two regimes (2020–21, 2023–24
   bulls); the Coinquant material (source 9) independently describes Donchian
   crypto profitability as dependent on a few large trends, and the card's own
   kill-condition #3 says the same. The lab has already lost its best candidate
   to one September carrying 78% of five years of profit. The screen must
   compute: share of total P&L from the best month / best 5% of trades,
   per-regime P&L (bull/bear/chop segmentation fixed a priori), and an
   effective-N estimate that discounts the ~1200 trades for cross-pair
   correlation — the nominal t≈7 implied by (1.0% / (5%/√1200)) is a fiction if
   effective N is a few hundred.

## Parameter priors

- **Entry/exit channel (10/5):** faster than every canonical reference.
  Donchian's original rule is ~4 weeks (~20 days); Turtle System 1 is 20-day
  entry / 10-day exit, System 2 is 55/20 (sources 2, 11); BLL's trading-range
  break uses 50–200-day extremes (source 1); tutorial implementations default
  to 20/10 or 20/55 (source 10). A 10/5 channel roughly doubles turnover versus
  20/10, doubling the cost drag on a thinner per-trade edge — the literature
  prior says *slower*. However, 10/5 is coherent with the card's stated ~7-day
  hold and the ~1200-trade count that the noise-floor screen requires, and it
  was fixed before seeing data. **Card values stay.** Noted, pre-data: if this
  survives to a later non-toy run, a slower channel is the literature-preferred
  variant — as a *new card*, not a tune.
- **Stop at -10%:** no direct literature anchor (Turtles used 2×ATR, which on
  crypto dailies is often near 8–12% — roughly consistent). Reasoned, not
  sourced. Stays.
- **Timeframe 1d, long-only, shift 1:** consistent with sources 7–9 (daily
  crypto trend works net of fees only in liquid names) and with lookahead
  hygiene. Stay.
- **Estimates (1.0% gross/trade, 5% sd, ~1200 trades):** anchored on the lab's
  own measurements with a stated haircut; Han et al. (source 7) suggests the
  *net* edge after realistic costs could be far below the gross figure, and the
  correlation-adjusted trade count is the softest of the three numbers. No
  pre-data reason to change any of them; they stay as screening inputs.

## Verdict

The premise is plausible: post-breakout drift is documented in equities (BLL
1992) and time-series momentum is the one momentum flavor with decent evidence
in crypto (Han et al.), though the 10/5 parameterization is faster than
anything the literature blesses. The single biggest risk is return
concentration compounded by correlation — one or two BTC-driven bull episodes
across 17 correlated pairs carrying nearly all P&L, making the nominal ~1200
trades worth a few hundred effective ones and the apparent edge a regime
artifact. The screen stage should look hardest at concentration diagnostics
(best-month and top-5%-of-trades P&L share, per-regime P&L, effective N under
cross-pair correlation) and at an all-in cost model with a thin-alt slippage
multiplier, with pessimistic gap-fill handling on the -10% stop.
