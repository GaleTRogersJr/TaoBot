# GR Software — Bittensor Subnet Trading Bot

Status: Windows monitor and alerts prototype now connects automatically to live Taostats prices and pool metrics using a Windows-user-protected saved credential. Each subnet's Details page includes on-demand TAO/alpha candlestick history with selectable timeframes and hover inspection. See [README.md](README.md) for current features and limitations, and [ROADMAP.md](ROADMAP.md) for the proposed delivery sequence.

## Ownership

- Project owner: final authority on scope, capital, and trading permissions.
- David: orchestrator and second in command; coordinates requirements, assignments, and review.
- Tyler (Codex): lead programmer; implements and tests approved scope.

These are the agreed team roles. Tyler implemented the first UI increment through a local programming subagent; David reviewed and verified it.

## Confirmed objective

Build a customizable bot specifically for trading Bittensor subnet assets. Users can choose metrics, data, and other information to inform strategies. The bot may execute trades only with the user's permission.

The first version is for the owner's personal trading. It must support both individual trade approval and automatic trading within explicitly approved limits. These product requirements do not authorize real trades now.

## Domain basis

Subnet staking exchanges TAO for a subnet's alpha; unstaking exchanges alpha for TAO. Execution must account for pool liquidity, price impact, fees, and changes between a quote and transaction execution. Validator/hotkey selection is part of specifying a stake position.

Reference: https://www.bittensor.com/docs/concepts/staking-pools

Actual SDK versions, network capabilities, and quote behavior must be verified before implementation.

## Confirmed first release and proposed later milestones

Deliver a Windows desktop program with a UI, subnet information from Taostats or a comparable provider, and configurable price alerts for any supported subnet. This first release precedes paper trading and AI work. A mobile app may follow later.

Current increment: unlimited Watch selection, fixed-price and percentage rise/fall/either-direction alerts, TAO/alpha prices, signed 24h change, a metrics Details view, secure remember/replace/forget controls, automatic saved-key reconnect, timestamp-preserving offline catalog cache and a bounded archive of observed polling snapshots. The owner requested a 30-second default and saved cadence, with six-hour name refreshes, request estimates and persisted rate-limit/authentication backoff. Settings explains that continuous 30-second monitoring exceeds the Free plan's monthly credits. Transient outages continue automatic recovery with delays capped at one hour, while provider Retry-After waits and rejected credentials remain respected. Cached data cannot trigger alerts. The 180-second freshness guard remains; provider delays and outages can pause alerts. David independently verified authenticated startup/restart with 128 non-root subnets and current price/change/liquidity/volume fields; real trading remains outside this increment.

After the monitor and alerts work reliably, add a realistic virtual-money simulator, train/evaluate AI trading candidates, and run multiple competing agents with separate virtual portfolios. Select agents through repeatable evaluation on unseen data and live paper trading, using returns, risk, costs, and reliability. Live execution remains a later, separately authorized stage.

Proposed capabilities:

- Select subnet watchlists and view timestamped market data.
- Configure strategy inputs, thresholds, sizing, and evaluation frequency.
- Start with measurable market inputs: price movements, liquidity, volume where available, and staking flows. Assess emissions and other subnet signals for availability and meaning before use.
- Make additional data sources and strategies extensible. News or model-generated signals remain optional future inputs requiring separate validation.
- Show why a signal occurred and which data and strategy version produced it.
- Simulate holdings and trades using execution-aware quotes, including fees and price impact. Record assumptions and unavailable data explicitly.
- Report performance in TAO; label any additional currency conversion and its source.

## Proposed permission and execution requirements

- Default to read-only or paper trading.
- Support both per-trade approval and bounded automatic trading, as selected by the owner.
- Automatic permission must specify wallet, network, allowed subnets, capital and order limits, strategy version, expiry, and revocation behavior.
- Apply independent limits for concentration, quote age, execution price, fees, and order frequency.
- Pause execution when data is stale, permissions are absent or expired, or transaction state cannot be reconciled.
- Provide an immediate stop control that prevents new submissions; already submitted transactions require reconciliation.
- Persist trade intent and transaction state to prevent duplicate submissions after retries or restarts.
- Keep private keys and seed phrases out of prompts and logs. Choose the wallet/signing design before live execution.
- Record proposals, approvals, rejected actions, submissions, confirmed results, and failures.

## First-release acceptance criteria (proposed)

1. Users can browse available subnets and configure watchlists without editing code.
2. Users can set, edit, pause, and delete price alerts with explicit units.
3. Alerts, preferences, and trigger history persist across restarts.
4. Stale or missing data cannot generate misleading price notifications.
5. Windows notifications, repeat-alert handling, and background tray monitoring work as documented.
6. The packaged first release cannot sign or submit live transactions.

## Decisions to resolve

- Initial strategy and subnet selection?
- Windows UI framework, screen design, and background-monitoring defaults?
- Data providers, history coverage, and access requirements?
- Wallet/signing integration and validator selection?

The owner authorized implementation of the Windows watchlist and alerts UI, followed by uploading the existing project to the TaoBot GitHub repository. No live trading permission or wallet connection is established by this brief.
