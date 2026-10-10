# GR Software — Bittensor Subnet Monitor and Trading Research

Planning date: October 9, 2026 (America/New_York).

This roadmap records the requested direction and proposed delivery gates. It does not authorize live trades. The first release is a Windows desktop program for personal use, with a UI and configurable subnet price alerts. AI research and simulated competition follow after that release works reliably.

## Delivery sequence

| Stage | User-facing result | Gate to advance |
| --- | --- | --- |
| 0. Data and design | Agreed screen layout and verified data source | API access, units, coverage, quotas, and refresh behavior established |
| 1. Windows monitor and alerts | Browse subnets, watch prices, configure alerts | Packaged program works; alert and restart behavior verified |
| 2. Data archive and simulator | Replay history and trade with virtual TAO | Accounting and execution assumptions independently checked |
| 3. AI candidates | Several distinct agents making simulated decisions | Versioned agents beat meaningful baselines on validation data |
| 4. Competition and forward testing | Leaderboard of independent virtual portfolios | Finalists pass untouched tests and live paper trading within risk limits |
| 5. Optional live trading | Selected agent proposes or executes permitted trades | Owner approval, signing design, reconciliation, and execution controls verified |
| 6. Future app | Mobile access to monitoring, alerts, and results | Reusable services plus hosting, authentication, and notification design |

Use milestone gates rather than promised dates. Estimate implementation after the data-access check and screen design; AI evaluation will also require elapsed market observation time.

## Stage 0 — Data access and UI design

Use Taostats' documented API as the first candidate. Keep a provider interface so another service or direct chain queries can be added without rewriting alerts or strategies. Retrieve supported data through the API; do not depend on scraping website layouts.

Before implementation, verify:

- Account/API-key access, allowed use and storage, plan quotas, rate limits, and costs.
- Current endpoint versions, response fields, pagination, price units, and data timestamps.
- Availability of subnet catalog/identities, pool prices, liquidity, volume, emissions, and historical records. Missing fields remain explicitly unavailable.
- Historical granularity and coverage for each field; do not treat sampled pool snapshots as complete intrablock price paths or historical volume.
- Handling for newly registered and deregistered subnets and reused subnet IDs. Track registration identity as well as netuid when available.
- Refresh interval consistent with provider limits; show observed data age rather than promising real-time updates.

Draft four initial screens: subnet browser/watchlist, subnet detail/chart, alert manager/history, and settings/data status. Portfolio and agent screens follow later.

## Stage 1 — Windows UI and price alerts (first release)

Build an installable or self-contained Windows program with readable labels, search by subnet ID/name, sortable prices, and watchlists. Show price in TAO per alpha by default. Add USD display/alerts only with a timestamped TAO/USD source and explicit units; pause USD alert evaluation if either input is stale.

Include available price changes, liquidity, and volume in the browser, plus charts where history is available. Label data source, latest update, and connection state.

Users can configure alerts for any listed subnet with available price data:

- Above/below a chosen price, with one-shot or repeating behavior.
- Several independent alerts per subnet, with edit, pause, and delete controls.
- In-app alert history, Windows notifications, and optional sound.
- Repeating alerts rearm after the condition clears, with a cooldown to prevent repeated notifications around the threshold.
- First valid observation already beyond a threshold triggers once and is labeled as already met; subsequent triggers use observed crossings.
- Persist settings, alert state, and history across restarts. Record source time and observation time on events.

Monitoring continues when minimized to the system tray. The computer must remain awake, connected, and running the monitor. Closing the monitor or powering off pauses monitoring; do not promise alerts for unobserved crossings. On resume, evaluate the latest valid sample and mark the gap. Retrospective gap analysis may be a later feature where sufficiently detailed data exists.

Acceptance gate:

1. Connect to the provider and browse its supported subnet catalog; paginate correctly.
2. Create and trigger both upward and downward alerts using controlled price sequences, then verify actual live-data refresh separately.
3. Verify equality, first observation, repeated crossings, cooldown, and restart persistence.
4. Stale, invalid, missing, or out-of-order samples cannot trigger misleading price alerts; connection status explains the issue.
5. Verify Windows notification and tray behavior, plus packaging on a clean Windows environment.
6. First release requires no trading wallet and contains no live-trade execution path.

## Stage 2 — Data archive and virtual trading

Start recording permitted timestamped data during Stage 1. Add historical imports and a documented field/coverage inventory. Keep immutable research snapshots so experiments are reproducible.

Provide configurable virtual starting capital, holdings, trade history, equity charts, realized/unrealized returns, and drawdown. Support manual simulated trades and simple automated strategy baselines before AI candidates.

Use two modes: accelerated historical replay and live paper trading against incoming data. The simulator must model fees, price impact, latency, liquidity limits, and partial/rejected fills where supported. Snapshot data alone cannot establish every historical executable fill; label approximations and test conservative cost scenarios. Model staking rewards and validator take separately when included, and keep their treatment identical across competitors.

Maintain separate pool/portfolio state per competitor. Within each simulation, an agent's trades must affect its modeled execution state; do not let one competitor's virtual order alter another's competition environment.

Gate: independently reconcile balances and trade costs, prove agents cannot overspend or submit duplicate orders, replay a fixed experiment reproducibly, and verify stale-data pauses.

## Stage 3 — AI research and training

Begin with a small set of distinct candidates rather than many copies of one prompt. Proposed starting group:

- Momentum strategy.
- Mean-reversion strategy.
- Liquidity/flow strategy.
- Trained predictive model with a bounded trading policy.
- Optional language-model analyst using timestamped structured inputs.

The first three are rule-based controls; they help establish whether learned agents add value. Training means fitting predictive models or policies to data, and possibly reinforcement learning in a validated simulator later. Supplying data to a pretrained model or changing its prompt is not itself model training. Building a large foundation model from scratch is outside this roadmap.

Start with price, returns, volatility, liquidity, volume/flows, and available emissions/validator inputs. Add news, social signals, or subnet business information only after defining provenance, availability time, and measurable contribution. More data is not automatically better.

All candidates produce structured buy/sell/hold proposals with subnet identity, size, input timestamps, strategy/model version, and reason. A shared risk engine decides admissibility independently of the agent. Runtime model choice is a separate research decision from the model used by Tyler to develop the software.

Training uses older data; validation uses later data; final testing uses a sealed, later period. Never give agents future candles, revised future-known indicators, or hindsight subnet selection. For language-model historical tests, account for possible knowledge of past outcomes from pretraining; live forward testing is especially important.

## Stage 4 — Agent competition and selection

Start with roughly 4–6 candidates, each with the same starting virtual TAO, eligible markets, decision cadence, input-availability rules, cost assumptions, and risk limits. Store exact versions and random seeds where applicable. Record model/API compute cost and operating latency separately from trading returns.

Use cash-in-TAO, buy-and-hold, and simple strategy benchmarks. Define scoring before the competition: net return after costs, maximum drawdown, risk-adjusted performance when sample size supports it, turnover, concentration, and reliability. A high return with unacceptable drawdown cannot win. Report marked portfolio value and estimated exit value where liquidity limits matter.

Track all candidates and failed experiments, not just winners. Limit repeated tuning against evaluation data. Include subnet delistings and historical eligibility to avoid only testing surviving subnets. Test several market periods and stress cases, then freeze finalists before the sealed evaluation. Any further tuning requires fresh evaluation data.

Run finalists in live paper trading. Require sufficient observations, relevant trades, and acceptable uncertainty rather than declaring success after a short winning streak. Competition can select robust candidates, but cannot guarantee future profit. Retain the option to select no agent if none beats the benchmarks within agreed risk limits.

Winners become nominated active paper-trading agents first. Use a stable incumbent and challengers; promotion is deliberate and reviewed, rather than automatic switching after daily rank changes.

## Stage 5 — Optional real-money execution

Only after separate owner authorization: add wallet signing and fresh chain execution quotes, start with individual trade approval, then support automatic trading under explicit limits. Permissions specify wallet/network, subnet scope, strategy version, capital/order limits, expiry, and revocation.

Before release, verify key isolation, price limits, transaction reconciliation after timeouts/restarts, duplicate prevention, failure recovery, and a stop control. Agents never override permission or risk limits. Continue paper challengers alongside any selected live agent.

## Stage 6 — Future mobile app

Keep data retrieval, alerts, simulation, strategy evaluation, and risk controls separate from the Windows UI. A future mobile interface can reuse those services, although the UI and mobile integrations will need their own implementation.

An always-on service is needed for notifications while the PC is off. Plan hosting, authentication, secure key handling, push notifications, synchronization, and costs when mobile work is authorized. A sensible first mobile release would display watchlists, alerts, and competition results.

## Proposed engineering organization

Tyler owns implementation/testing; David coordinates scope and review; the owner sets product priorities and trading permissions. Sol/High is the recommended development default, with additional review for difficult architecture and execution controls; no model settings have been changed by this document.

Keep a local database for configuration, alerts, and records initially. Select the Windows UI framework after a small packaging/layout prototype; keep AI training in separate jobs so it cannot freeze monitoring. Version data providers and experiments. Bound storage and compute usage as the archive and competition grow.

Next concrete work package: verify Taostats access/schema and create the four-screen UI design, then implement only the Windows monitor and alerts milestone. No separate programming assignment is dispatched by this plan.

## Sources and remaining dependencies

Verified documentation supports API feasibility; no authenticated data request has been made yet. Account-specific quotas, costs, history completeness, storage permissions, and actual field quality remain to be checked.

- [Taostats API reference and authentication](https://taostats.io/docs/new).
- [Getting a Taostats API key](https://taostats.io/docs/start-here/getting-started-with-taostats-api).
- [Current subnet pool fields](https://taostats.io/docs/api-reference/subnet/get-pool-latest).
- [Historical pool snapshots and sampling](https://taostats.io/docs/new/subnets/get-subnets-pools-history).
- [Bittensor staking, pools, and execution mechanics](https://www.bittensor.com/docs/concepts/staking-pools).
