# APIx Collection Operations & Scheduling Guide

This guide documents operational procedures for running scheduled, resilient daily airfare data collection for the **Real-Time Indian Domestic Airfare Price Index (APIx)**.

---

## 1. Daily Collection Architecture

Daily collection runs across the configured observation grid:
- **Routes**: 20 DGCA top city-pairs (10 bidirectional pairs).
- **Lead Windows**: T+1, T+7, T+15, T+30, T+45 days.
- **Schedule**: Once daily during the low-traffic window (recommended **02:00 IST / 20:30 UTC**).
- **Audit Logging**: Exactly one `collection_runs` record is generated per source per daily run, tracking `records_found`, `records_saved`, `records_rejected`, `blocked_count`, and `captcha_count`.
- **Mode Isolation**: Mock/synthetic data (`is_synthetic=True`) and real/recorded data (`is_synthetic=False`) are strictly isolated and never execute in the same collection run.

---

## 2. Windows Task Scheduler Setup

### Option A: PowerShell Command (Automated Setup)

Run the following command in an Administrator PowerShell window from the project root:

```powershell
# Define paths
$ProjectPath = "C:\Users\satye\OneDrive\Desktop\SIH2026-AIRFARE"
$PythonExe = "$ProjectPath\venv\Scripts\python.exe"
$ScriptArgs = "-m scripts.daily_collection --mode mock"

# Create action
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $ScriptArgs -WorkingDirectory $ProjectPath

# Trigger daily at 02:00 AM IST
$Trigger = New-ScheduledTaskTrigger -Daily -At 2:00AM

# Execution settings
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# Register task
Register-ScheduledTask -TaskName "APIx_Daily_Airfare_Collection" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Runs daily APIx airfare collection across active grid cells"
```

### Option B: Windows GUI (`taskschd.msc`)

1. Press `Win + R`, type `taskschd.msc`, and hit **Enter**.
2. In the right panel, click **Create Task...**.
3. **General Tab**:
   - Name: `APIx_Daily_Airfare_Collection`
   - Select: `Run whether user is logged on or not` (or `Run only when user is logged on` for dev).
4. **Triggers Tab**:
   - Click **New...** $\to$ **Daily**, Start at `02:00:00 AM`, Recur every `1` days.
5. **Actions Tab**:
   - Click **New...** $\to$ Action: `Start a program`.
   - Program/script: `C:\Users\satye\OneDrive\Desktop\SIH2026-AIRFARE\venv\Scripts\python.exe`
   - Add arguments: `-m scripts.daily_collection`
   - Start in: `C:\Users\satye\OneDrive\Desktop\SIH2026-AIRFARE`
6. **Settings Tab**:
   - Check `Run task as soon as possible after a scheduled start is missed`.
   - Click **OK** to save.

---

## 3. Linux / Unix Cron Setup

For Linux production servers running cron, edit the user crontab (`crontab -e`):

```bash
# Set timezone to Indian Standard Time (IST)
CRON_TZ=Asia/Kolkata
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# Run APIx daily collection every day at 02:00 AM IST
0 2 * * * cd /opt/apix && /opt/apix/venv/bin/python -m scripts.daily_collection >> /opt/apix/logs/daily_collection.log 2>&1
```

---

## 4. APScheduler Background Daemon Service

To run the continuous Python daemon service (which listens to SIGINT/SIGTERM):

```bash
# Run in foreground / background supervisor (e.g. systemd or supervisord)
python -m scraper.scheduler
```

The daemon reads schedule parameters from [`config/collection.yaml`](file:///c:/Users/satye/OneDrive/Desktop/SIH2026-AIRFARE/config/collection.yaml):
```yaml
scheduler:
  cron_expression: "0 2 * * *"  # 02:00 IST
  timezone: "Asia/Kolkata"
```

---

## 5. Coverage Monitoring & Audit Reporting

To monitor collection health, run success rates, and verify grid cell population over the last 7 days:

```bash
# View human-readable terminal table
python -m scripts.coverage_report --days 7

# Filter by a specific source or route
python -m scripts.coverage_report --source EaseMyTrip --route BOM-DEL

# Export as JSON for automated monitoring dashboards
python -m scripts.coverage_report --days 7 --json > reports/coverage_latest.json

# Export as Markdown summary
python -m scripts.coverage_report --days 14 --format markdown
```

### Key Metrics Tracked:
- **Success Rate**: $\frac{\text{Days with Valid Quotes}}{\text{Sliding Window Days}} \times 100\%$
- **Sold-Out Share**: $\frac{\text{Sold-Out Observations}}{\text{Total Observations}} \times 100\%$
- **Block & CAPTCHA Counts**: Aggregated from `collection_runs.blocked_count` and `collection_runs.captcha_count`.

---

## 6. Circuit Breaker Operation & Troubleshooting

Each source is protected by an automatic `CircuitBreaker`:
- **Threshold**: 3 consecutive blocks/challenges trips the circuit from `CLOSED` $\to$ `OPEN`.
- **Action**: When `OPEN`, subsequent grid cells for that source are skipped during the run to prevent IP burns or wasted requests.
- **Cooldown & Recovery**: After 300 seconds (5 minutes), the circuit transitions to `HALF_OPEN` to probe endpoint health. A successful quote returns it to `CLOSED`.

### Checking Tripped Sources:
Check `collection_runs` where `status = 'blocked'`:
```sql
SELECT source_id, status, blocked_count, captcha_count, error_message, start_time
FROM collection_runs
WHERE status = 'blocked'
ORDER BY start_time DESC
LIMIT 10;
```
