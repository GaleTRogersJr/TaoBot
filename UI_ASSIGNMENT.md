# Tyler — Windows Watch UI and Price Alerts

Owner instruction: begin implementing a clean, simple Windows UI in `C:\TAO Trading Bot`. David coordinates and reviews; Tyler is the lead programmer. This work implements the first monitor/alerts milestone.

## Required experience

- A searchable subnet picker supports selecting any number of subnets and adding them to a "Watch" window/view. No arbitrary watchlist cap; make large lists scrollable. Prevent duplicates by stable subnet identity and allow removal.
- Each watched subnet shows its name and subnet ID, current TAO per alpha value, and signed percentage gained/lost over the last 24 hours. Use readable positive/negative styling as well as signs. Never display dollar prices.
- Each watch entry provides an obvious action to create/manage multiple alerts.
- Target-price alerts: user selects at-or-above or at-or-below and enters a positive TAO-per-alpha value. Example: Engy reaching 0.3 TAO per alpha. Resolve subnet identity from data; do not invent Engy's subnet ID or current value.
- Percentage alerts: user chooses rise, fall, or either direction and a positive percentage. Price at alert creation is the fixed reference, clearly shown with its capture time. A 10% rise from 0.2 triggers at 0.22; a 10% fall triggers at 0.18; either direction triggers at or above 0.22 or at or below 0.18. This is distinct from the 24-hour change shown on the watch entry. A later rolling-window percentage option can be added separately.
- Alerts support edit, pause/resume, delete, and one-shot/repeating mode. Repeating alerts rearm when the condition clears and use a cooldown to avoid spam; persist trigger state.
- Include alert history and an in-app notification. Implement native Windows notifications where available, with a test notification and visible fallback; clearly document any deferred integration.
- Persist watchlist, alerts, and alert history across restarts.
- Show loading, empty, connection error, stale data, and missing 24-hour change states explicitly. Missing values are not zero. Timestamp the data.

## Data and implementation boundaries

- Inspect applicable AGENTS.md first. Preserve the existing brief/roadmap and unrelated work.
- Choose a practical desktop framework and keep UI, data provider, storage, and alert evaluation separate. Verify the Windows runtime and packaging approach available here.
- Provide a Taostats provider seam and settings for API access. If live data cannot be retrieved without a key, deliver a clearly labeled demo mode and disclose that live connectivity is pending. Do not present sample values as live prices.
- Percentage references must come from a valid, fresh sample. Never evaluate alerts on stale, missing, invalid, or out-of-order prices. Target equality counts as reaching the target.
- For the first valid sample already beyond an absolute target, emit one labeled "target already met" event. Do not imply an observed crossing. Resume after data gaps with a clearly labeled current observation.
- Monitoring is local: it operates while the app is running and the PC is awake. Explain this plainly in settings/help.
- No wallet integration, keys/seed phrases, transaction submission, or AI trading in this assignment. No commits or publishing requested.

## Verification and handoff

Test meaningful alert behavior (rise/fall, absolute targets, equality, stale inputs, repeated notifications, editing and persistence), watchlist uniqueness/persistence, and 24-hour change handling. Verify the actual Windows UI launches and inspect its layout when tools permit. Provide launch instructions and a runnable application, report tests and limitations, and distinguish demo validation from authenticated live API validation.

If the chosen framework or notification integration requires an unavailable dependency, deliver the safest runnable implementation and report the exact remaining dependency. Do not leave only a design document.

## Execution record

- GR Software assignment ID: `1b94bd6c-6817-48b9-bdbe-a47ff5019c94`.
- Assignment was recorded, but the GR Software dispatch call returned an error. Inspection showed pending status and no execution or recorded approval. This record must not be described as successfully dispatched through that bridge.
- David started a local programming subagent named `/root/tyler` under the owner's instruction to begin this UI work. That agent is implementing the application in this workspace.
- Tyler implemented the native Windows UI and separate provider, alert, storage, and notification modules.
- David reviewed application code and independently checked target equality at 0.3, one-shot suppression, percentage reference arithmetic, and signed 24-hour display.
- Visual review of the Watch screen, alert editor, and Settings passed after correcting Windows display-scaling and layout issues. UI smoke exercised 250 watched subnets and alert form creation/pause/resume.
- All 24 focused alert/provider/storage tests passed. The actual windowless Windows launcher opened the UI, loaded eight demo samples, wrote `qa/launcher-smoke-report.json`, and closed normally in its verification mode.
- Authenticated Taostats data and visible Windows banner delivery remain unverified; demo validation is clearly identified. Native tray registration passed on the desktop, with taskbar/in-app fallbacks when unavailable.
- First UI increment is ready for owner review. Launch with `Launch Subnet Watch.cmd`; `README.md` records usage, verification, and prototype limits. No live trades or commits were made.
- Follow-up: either-direction percentage alerts were implemented and verified, bringing the focused suite to 29 passing tests.
- The owner subsequently authorized uploading the existing program and roadmap to `GaleTRogersJr/TaoBot`. This authorization supersedes the original assignment's restriction on commits and publishing for that upload only.
- Latest increment: the owner authorized saved Taostats access and all-subnet data. Windows-user-scoped DPAPI protection, blank masked replacement/secure remember/forget controls, automatic reconnect, a pool-metrics Details view, timestamp-preserving catalog cache and a bounded polling archive are implemented. No key is stored in source or SQLite.
- The owner requested 30-second polling, now the default and saved cadence; friendly names refresh every six hours. Settings explains that continuous monitoring at this cadence exceeds the Free plan's 10,000 monthly credits (estimated 89,404 requests/31 days at one page per endpoint). Provider rate-limit deadlines survive restart and unchanged settings. Transient failures continue automatic recovery with backoff capped at one hour; longer Retry-After waits remain honored. Rejected credentials require replacement. Cached data never triggers alerts, and the 180-second freshness guard remains unchanged.
- All 57 focused tests passed. Actual form/layout smoke passed for the watchlist, either-direction alert editor, saved-key Settings and numeric-metrics Details view, including 250 watched subnets at the minimum window size. David visually reviewed the new screens.
- David independently verified actual DPAPI protection and authenticated automatic startup/restart with 128 non-root subnet prices, daily changes, liquidity and volume. Restored cached samples retained their original timestamps and could not become fresh merely by loading. The actual key was absent from all nonignored source files and SQLite.
- Visible Windows notification banner delivery, full provider data quality and provider credit accounting remain outside these checks. No real trades, commits or uploads were performed for this latest increment.
- Candlestick increment: Details now has Price chart and Metrics tabs, with TAO/alpha OHLC candles, three timeframes, local timestamps and hover inspection. History is loaded on demand, session-cached for five minutes and spaced at least 30 seconds apart. Historical data never evaluates alerts. Pending chart waits cancel when closed; provider rate-limit waits persist even if Details closes during the network request. Native live-chart drawing, hover and reopening from cache were verified with 168 hourly bars for subnet 19. The focused suite now contains 68 tests, alongside the existing native UI smoke.
