# GR Software · Subnet Watch

A native Windows desktop prototype for choosing subnets, watching **TAO per alpha** prices and configuring price alerts. It contains no wallet connection, signing or trade execution.

## Open the program

Double-click **Launch Subnet Watch.cmd** in this folder. It starts a normal desktop window without a terminal staying open.

This checkout uses the Python runtime bundled with the Codex desktop installation when available. The application requires **Python 3.11 or newer with Tk** and otherwise uses only its standard library. For another machine, install Python with Tk and set `GR_SUBNET_PYTHON` to the full `python.exe` path, or run `python main.py` from this folder. No standalone installer or bundled executable has been produced yet.

## Watch and alerts

1. Search the left list by subnet name or ID. Click rows (or press Space on selected rows) to toggle checkmarks. Choose as many as you want, then **Add selected to Watch**. Lists scroll; watchlist entries are unique. Removing a subnet also removes its alerts, preserving its history.
2. The Watch window shows name/ID, current **TAO / alpha**, signed **24h change**, and active alert count. Missing daily change displays **Unavailable**, rather than zero. Select a row to see its sample timestamp.
3. Select a watched subnet and choose **Price alert**. Create any number of alerts: a specific positive price **at or above / at or below**, or a percentage **rise / fall / either direction** from the latest valid price at save time. Equality counts as reaching the target.
4. Percentage references remain fixed. For example, a 10% rise from 0.2 triggers at 0.22 TAO per alpha. **Either direction** at 10% triggers at or above 0.22 **or** at or below 0.18. The description displays both boundaries and each event records the boundary actually reached. Either-direction repeats rearm only when a fresh price returns inside the band; moving straight from above to below it does not rearm. Fall and either-direction percentages must be less than 100%. This does **not** mean the subnet's displayed 24h change. The captured reference and time appear in Alerts. Editing a percentage alert captures a new reference and resets its trigger state; editing a completed one-shot alert starts it again.
5. Alerts can be edited, paused, resumed or deleted. A one-shot completes after its first notification. A repeating alert rearms only after a valid observation clears its condition, and waits for its cooldown before notifying again. If a condition returns during cooldown and remains true, the next fresh observation after cooldown can notify.
6. History preserves the observed price, condition, sample/observation times, source and event description. The first sample beyond a target says **target already met**, rather than claiming an observed crossing. After a restart/data gap, current observations are explicitly labeled.

The program updates in the background without freezing the interface. Data older than three minutes, future timestamps over 30 seconds ahead, missing/invalid prices, repeated samples and out-of-order timestamps cannot generate alerts. Old displayed values are marked stale. Check your Windows clock if timestamp validity is unexpected. Polling cannot observe every crossing between updates; monitoring resumes from the latest sample after a gap.

## Data source

The initial default is **DEMO DATA**, prominently labeled. All demo subnet names, IDs, prices and changes are synthetic; they have no real market mapping. Engy's ID and live price have not been guessed or seeded. Demo selection is limited to the eight synthetic examples, while the live provider can paginate through every available subnet without a watchlist cap.

In **Settings**, choose **Taostats API**, enter your API key and choose **Save & connect**. Keys stay in process memory, are never saved in SQLite and must be entered again after restarting. There is no automatic fallback from a failed live connection to demo data. Live and demo watchlists, alerts and history are kept separate by provider identity.

The adapter follows the official documented HTTPS endpoints:

- `/api/dtao/pool/latest/v1`: paginated latest pools, source `timestamp`, `netuid`, `price` already in TAO per alpha, and `price_change_1_day` already in percent. No dollar conversion or rao scaling is applied to these fields.
- `/api/subnet/identity/v1`: paginated `subnet_name` join by netuid, refreshed hourly. If friendly-name lookup fails, known or pool names remain available and prices can still load; a warning explains it.

Requests send the raw API key in the `Authorization` header to `https://api.taostats.io`. Redirects are refused to avoid forwarding credentials. Each page uses `limit=200`, following `pagination.next_page` until null. Timeouts, authentication failures, pagination/schema errors and rate limits are visible in the UI. Default refresh is 60 seconds, configurable from 30 to 3600; choose a cadence that fits your plan. A request can take longer than the configured cadence because requests run serially and refresh scheduling starts after completion.

Authenticated live connectivity, plan quotas and actual provider data quality **have not been tested** because no API key was provided. This adapter uses the still-documented `/api/.../v1` endpoint family; the newer `/v1/...` family can be added through the provider seam after its schema/access is verified. Subnet identity is currently provider + netuid; detecting reused netuids through registration identity is a future hardening item before relying on long-lived production alerts.

Official references checked October 9, 2026:

- [Current pool schema, units and percentage fields](https://taostats.io/docs/api-reference/subnet/get-pool-latest)
- [Subnet identity names](https://taostats.io/docs/api-reference/subnet/get-subnet-identity)
- [API-key access](https://taostats.io/docs/start-here/getting-started-with-taostats-api)

## Notifications, storage and operation

Events appear in-app and in **History**. On Windows, the program registers a native tray icon and requests Windows balloon notifications. **Settings → Test notification** tests the request path. Windows notification settings, Focus Assist/Do Not Disturb or shell policy can suppress banners, so native request success is not proof of visible delivery. If the shell/tray integration is unavailable, in-app/history notifications remain available and **Hide to tray** minimizes to the taskbar.

**Hide to tray** keeps monitoring active; click the tray icon to restore the window. Closing the window exits the program. Monitoring only works while the program is running and your computer is awake and connected. There is no always-on remote service.

`data/watch.sqlite3` stores watchlists, preferences, alert trigger state and history beside this portable checkout. State and event records commit in one SQLite transaction before notification delivery. Keep the folder writable. Back up the data folder while the program is closed. Do not run multiple copies against the same database; single-instance enforcement is not yet implemented. Notification delivery is best-effort: a crash after committing an event but before sending its banner leaves the event in History.

## Verification

Run the focused suite with `python -m unittest discover -s tests -v`. It covers target equality/direction, percentage references and either-direction boundaries, one-shot/rearm/cooldown, stale/invalid/duplicate/out-of-order/future samples, gap labels, edited alerts, persistence, 1001 unique watch entries, missing daily changes, documented units, pagination and optional name-lookup failure. All **29 tests passed**.

`python tests/ui_smoke.py` opens the actual Windows UI, creates both alert types through their forms, checks direction/reference persistence including saving and reopening **Either direction**, exercises pause/resume and loads **250 watched subnets** at the minimum viewport. It captures only the application's own windows and produces `qa/ui-smoke-report.json` plus screenshots. Pillow is optional QA tooling only and is available in the bundled runtime. Sandbox desktop capture may be incomplete; successful native captures and tray registration were verified on the Windows desktop. Visible native notification delivery was not independently verified.

`powershell -NoProfile -ExecutionPolicy Bypass -File '.\Launch Subnet Watch.ps1' -VerifyLaunch` exercises the real windowless launcher, waits for the window/data initialization, writes `qa/launcher-smoke-report.json` and closes the test window.

## Structure

- `subnet_watch/app.py`: native Tk screens, forms and background refresh coordination.
- `subnet_watch/core.py`: Decimal prices, freshness and alert evaluation.
- `subnet_watch/providers.py`: synthetic demo and documented read-only Taostats adapter.
- `subnet_watch/storage.py`: local SQLite state and atomic alert history.
- `subnet_watch/notifications.py`: optional Windows tray/balloon support.

This is the first functional UI increment. Standalone packaging, charts, wider subnet metrics, registration identity hardening and full authenticated live validation remain future work. AI training, simulated trading and any real trading are outside this increment.
