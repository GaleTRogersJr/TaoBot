# GR Software · Subnet Watch

A native Windows desktop prototype for choosing subnets, watching **TAO per alpha** prices and configuring price alerts. It contains no wallet connection, signing or trade execution.

## Open the program

Double-click **Launch Subnet Watch.cmd** in this folder. It starts a normal desktop window without a terminal staying open.

This checkout uses the Python runtime bundled with the Codex desktop installation when available. The application requires **Python 3.11 or newer with Tk** and otherwise uses only its standard library. For another machine, install Python with Tk and set `GR_SUBNET_PYTHON` to the full `python.exe` path, or run `python main.py` from this folder. No standalone installer or bundled executable has been produced yet.

## Watch and alerts

1. Search the left list by subnet name or ID. Click rows (or press Space on selected rows) to toggle checkmarks. Choose as many as you want, then **Add selected to Watch**. Lists scroll; watchlist entries are unique. Removing a subnet also removes its alerts, preserving its history.
2. The Watch window shows name/ID, current **TAO / alpha**, signed **24h change**, and active alert count. Missing daily change displays **Unavailable**, rather than zero. Select a row to see its sample timestamp, or choose **Details → Price chart** for candlesticks and **Details → Metrics** for available price changes, liquidity, market capitalization, reserves, staked alpha, 24h volumes/trade counts and source block. All monetary information is in TAO or subnet alpha, with units labeled.
3. Select a watched subnet and choose **Price alert**. Create any number of alerts: a specific positive price **at or above / at or below**, or a percentage **rise / fall / either direction** from the latest valid price at save time. Equality counts as reaching the target.
4. Percentage references remain fixed. For example, a 10% rise from 0.2 triggers at 0.22 TAO per alpha. **Either direction** at 10% triggers at or above 0.22 **or** at or below 0.18. The description displays both boundaries and each event records the boundary actually reached. Either-direction repeats rearm only when a fresh price returns inside the band; moving straight from above to below it does not rearm. Fall and either-direction percentages must be less than 100%. This does **not** mean the subnet's displayed 24h change. The captured reference and time appear in Alerts. Editing a percentage alert captures a new reference and resets its trigger state; editing a completed one-shot alert starts it again.
5. Alerts can be edited, paused, resumed or deleted. A one-shot completes after its first notification. A repeating alert rearms only after a valid observation clears its condition, and waits for its cooldown before notifying again. If a condition returns during cooldown and remains true, the next fresh observation after cooldown can notify.
6. History preserves the observed price, condition, sample/observation times, source and event description. The first sample beyond a target says **target already met**, rather than claiming an observed crossing. After a restart/data gap, current observations are explicitly labeled.

The program updates in the background without freezing the interface. Data older than three minutes, future timestamps over 30 seconds ahead, missing/invalid prices, repeated samples and out-of-order timestamps cannot generate alerts. Old displayed values are marked stale. Check your Windows clock if timestamp validity is unexpected. Polling cannot observe every crossing between updates; monitoring resumes from the latest sample after a gap.

## Data source

The initial default is **DEMO DATA**, prominently labeled. All demo subnet names, IDs, prices and changes are synthetic; they have no real market mapping. Engy's ID and live price have not been guessed or seeded. Demo selection is limited to the eight synthetic examples, while the live provider can paginate through every available subnet without a watchlist cap.

In **Settings**, choose **Taostats API**, enter your API key and choose **Save & connect**. **Remember securely for this Windows user** saves an encrypted Windows DPAPI credential for automatic reconnect on launch. No plaintext fallback exists. The key is never stored in SQLite, source or logs. Another Windows user cannot normally decrypt the file; any program running as your Windows account can access it, so this is user-account protection rather than isolation from your own applications. The replacement field is masked and opens blank; leave it blank to keep the current credential. **Forget saved key & disconnect** removes the saved credential and clears the active connection. Turning remembering off uses a session-only key and removes the saved copy. Choosing demo leaves a remembered live key available for a later switch back.

The owner's Taostats Free-plan key has been provisioned securely on this Windows account, so this checkout reconnects to live data by default. There is no automatic fallback from a failed live connection to demo data. Live and demo watchlists, alerts and history remain separate.

The adapter follows the official documented HTTPS endpoints:

- `/api/dtao/pool/latest/v1`: paginated latest pools for every subnet, source `timestamp`/block, price already in TAO per alpha, and 1h/24h/7d/30d changes already in percent. The same response provides liquidity, market capitalization, TAO/alpha reserves, staked alpha, TAO total/buy/sell volume and buy/sell/buyer/seller counts. Documented rao-valued balances and volumes are divided by 1,000,000,000; price and percentage fields are not scaled. Missing, negative balances and invalid counts display **Unavailable**.
- `/api/subnet/identity/v1`: paginated `subnet_name` join by netuid, refreshed every six hours. Names and their lookup timestamp persist across restarts. If lookup fails, known or pool names remain available; a warning explains it. The Metrics tab uses existing pool data without extra requests.
- `/api/dtao/tradingview/udf/history`: on-demand subnet OHLC history, using `SUB-{netuid}` and the documented resolutions/time-range parameters. Details defaults to hourly candles over seven days; 15-minute candles over 24 hours and daily candles over 30 days are also available. Prices remain in TAO per alpha. Hover shows open/high/low/close, local time and whether the newest candle is still forming. Time gaps are preserved; missing candles are never invented. Historical bars are display-only and cannot trigger alerts.

Charts load when Details opens or a timeframe is selected. **Refresh chart** explicitly requests newer history; the chart does not automatically poll with the 30-second Watch updates. A session cache reuses up to 32 recent subnet/timeframe views for five minutes. History requests are at least 30 seconds apart across subnets, and pending timeframe choices load after that wait. Closing the window cancels pending requests; a request already sent may finish. Rate-limit waits apply to both chart requests and price monitoring, including when Details closes mid-request. Chart access failures are shown in the chart without replacing live prices with demo data. Demo subnets have no real candle history. Chart requests add to API usage beyond the polling estimate below.

Requests send the raw API key in the `Authorization` header to `https://api.taostats.io`. Redirects are refused to avoid forwarding credentials. Each page uses `limit=200`, following `pagination.next_page` until null. Default price polling is **30 seconds**, as requested by the owner, configurable from 30 to 3600. Existing explicitly saved cadences remain intact; the owner's saved setting was separately changed to 30. With one pool page and one name page, a 31-day continuous estimate is **89,404 requests**, assuming one credit per request. The confirmed Free plan includes [5 credits/minute and 10,000 credits/month](https://taostats.io/docs/understanding-taostats/taostats-pro/your-taostats-account), so continuous 30-second monitoring exceeds its monthly allowance. At 300 seconds the estimate is 9,052 requests. Settings uses the last observed page counts; retries, manual refreshes, more pages and actual provider credit charging can increase usage. This is an estimate, not a quota guarantee. Each refresh retrieves all pool pages regardless of watchlist size. Completion schedules the next interval, so slow requests can make observations farther apart. Faster polling does not change the provider's own data publication frequency.

HTTP 429 honors numeric or HTTP-date `Retry-After`, including waits longer than one hour. Network/server failures back off exponentially, capped at one hour; automatic recovery continues at that slower cadence during a prolonged outage. A successful refresh restores normal polling. HTTP 401/403 stops automatic requests until a replacement key is provided. Polling deadlines/auth pauses persist across restarts; saving settings with the same key does not bypass them. Errors stay visible rather than switching to demo. No background sleep blocks the UI.

Authenticated automatic startup and restart were independently verified on the owner's Windows account: **128 non-root subnets**, all with price, 24h change, liquidity and TAO volume; all prices were fresh at the first observation. This verifies the connection and those fields, not comprehensive provider accuracy or plan quota accounting. The adapter uses the documented `/api/.../v1` endpoints. Subnet identity remains provider + netuid; registration identity hardening is a future item. A subnet missing from a complete refresh is removed from the current catalog and has unavailable price/paused alerts in Watch; failed partial refreshes preserve the previous catalog.

Official references checked October 9, 2026:

- [Current pool schema, units and percentage fields](https://taostats.io/docs/api-reference/subnet/get-pool-latest)
- [Subnet identity names](https://taostats.io/docs/api-reference/subnet/get-subnet-identity)
- [Subnet OHLC history and resolutions](https://taostats.io/docs/api-reference/tradingview/get-tradingview-udf-history)
- [API-key access](https://taostats.io/docs/start-here/getting-started-with-taostats-api)

## Notifications, storage and operation

Events appear in-app and in **History**. On Windows, the program registers a native tray icon and requests Windows balloon notifications. **Settings → Test notification** tests the request path. Windows notification settings, Focus Assist/Do Not Disturb or shell policy can suppress banners, so native request success is not proof of visible delivery. If the shell/tray integration is unavailable, in-app/history notifications remain available and **Hide to tray** minimizes to the taskbar.

**Hide to tray** keeps monitoring active; click the tray icon to restore the window. Closing the window exits the program. Monitoring only works while the program is running and your computer is awake and connected. There is no always-on remote service.

`data/watch.sqlite3` stores watchlists, preferences, alert trigger state/history, latest complete catalog and a bounded archive of polled snapshots. Cached records preserve original source **and** observation timestamps. They are labeled cached/waiting and can never evaluate alerts or provide a percentage reference, even if recently saved. Live confirmation can replace a cached record at the same source timestamp; alert trigger-state checks still suppress duplicate events. Cached data never becomes fresh merely by reopening the app.

The three-minute freshness guard remains unchanged. Rate limits, outages or delayed provider timestamps can still make prices stale even with 30-second polling. Cached values are display-only when offline, and monitoring still requires the app running and PC awake.

The compressed polling archive retains at most **seven days, 2,016 batches and 50MiB of compressed payloads**, deleting older batches to meet all limits. At 30-second cadence the batch limit covers roughly 16.8 hours; slower requests or pauses extend that time span. This records our observed polling samples, not a complete historical dataset, executable quotes or all intrablock crossings. SQLite file size may retain freed pages for reuse after eviction. No extra historical API requests are made. The Windows-user-protected credential is stored separately in `data/watch.taostats.dpapi`, excluded from Git. DPAPI files are not portable credentials for another Windows account.

State and event records commit in one SQLite transaction before notification delivery. Keep the folder writable and back up data while the program is closed. Do not run multiple copies against the same database; single-instance enforcement is not yet implemented. A crash after committing an event but before sending its banner leaves the event in History.

## Verification

Run the focused suite with `python -m unittest discover -s tests -v`: **68 tests passed** for this increment. It covers alert rules, credential save/replace/delete/failure behavior through injected protection, wrong-user/platform failures, metric units/nulls, pagination, cache timestamps and no cached alerts, archive bounds, continued outage recovery and retry/backoff/auth pauses, startup auto-loading and masked settings. Candle checks cover chronological OHLC validation, TAO units, cache reuse/expiry/bounds, request spacing, native drawing/hover/resize, forming/flat prices, closing during loading, connection changes and rate limits after the chart closes. It includes the existing 1001-entry persistence test and either-direction alert tests. Real Windows DPAPI encryption/decryption was independently verified using the owner-provided key; it was absent from the encrypted file's plaintext content and SQLite. No test fixture contains a real API key.

Authenticated candle history was verified for subnet 19 at all three timeframes: 96 fifteen-minute, 168 hourly and 30 daily bars. Native chart drawing, hover details and reopening from cache passed; `qa/live-chart-report.json` records the results and `qa/live-candlestick-details.png` shows the actual chart. These QA artifacts are ignored and contain no credential. This verifies the integration, not all historical provider values or chart access for every subnet.

`python tests/ui_smoke.py` opens the actual Windows UI with synthetic data, verifies both alert forms, **Either direction**, pause/resume, metrics Details and Free-plan Settings, and loads **250 watched subnets** at the minimum viewport. It captures only the application's own windows and produces `qa/ui-smoke-report.json` plus screenshots. Pillow is optional QA tooling only. Native captures/tray registration were verified on the Windows desktop. Visible notification-banner delivery remains unverified. The independent live startup/restart evidence is in `qa/live-connection-report.json` (ignored, no credential).

`powershell -NoProfile -ExecutionPolicy Bypass -File '.\Launch Subnet Watch.ps1' -VerifyLaunch` exercises the real windowless launcher, waits for the window/data initialization, writes `qa/launcher-smoke-report.json` and closes the test window.

## Structure

- `subnet_watch/app.py`: native Tk screens, forms and background refresh coordination.
- `subnet_watch/core.py`: Decimal prices, freshness and alert evaluation.
- `subnet_watch/providers.py`: synthetic demo and documented read-only Taostats adapter.
- `subnet_watch/storage.py`: local SQLite state and atomic alert history.
- `subnet_watch/notifications.py`: optional Windows tray/balloon support.
- `subnet_watch/credentials.py`: Windows-user-scoped DPAPI storage and trusted provisioning helper.
- `subnet_watch/polling.py`: request cadence, budget estimate and retry/backoff policy.
- `subnet_watch/candles.py` and `subnet_watch/chart.py`: validated OHLC history, bounded session cache and native candlestick drawing/inspection.

This increment connects the UI to live Taostats prices/metrics and on-demand candlestick charts with secure automatic reconnect. Standalone packaging, registration identity hardening and broader historical validation remain future work. AI training, simulated trading and real trading are outside this increment.

Trusted local provisioning without exposing a key in command arguments is supported by `subnet_watch.credentials.provision_taostats(key, database_path)`. It encrypts the supplied hidden-input key, selects live mode, sets 30-second cadence and clears prior authentication/backoff state. It does not itself contact the provider; the next app launch does. Never place a key literal in a script, shell argument, Git file or report.
