"""
PROJECT 3: Fraud & payments dashboard + metric dictionary + data-anomaly triage (synthetic data).

Outputs
  dashboard.html            self-contained dashboard (charts embedded)
  weekly_kpis.csv           weekly metrics   -> import into Tableau Public / Looker Studio / Sheets
  daily_data_quality.csv    daily row counts and duplicate rates
  data_quality_incidents.csv  anomalies the script detected
  (metric_dictionary.md is written by hand and lives next to this file)
Usage: python3 build_dashboard.py
"""
import base64
import io
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

here = Path(__file__).parent
con = sqlite3.connect(here.parent / "data" / "fraud.db")
MATURE_BEFORE = "2026-08-24"      # chargebacks take up to 30 days to arrive; later cohorts are incomplete

# ------------------------------------------------------------- weekly KPIs (SQL does the heavy lifting)
signup_weekly = pd.read_sql_query("""
    WITH first_dep AS (
        SELECT user_id, MIN(deposit_ts) AS first_dep_ts
        FROM deposits WHERE status IN ('success','chargeback') GROUP BY user_id)
    SELECT STRFTIME('%Y-%m-%d', DATE(u.signup_ts, 'weekday 0', '-6 days')) AS week_start,
           COUNT(*)                                                    AS signups,
           COUNT(fd.user_id)                                           AS depositors,
           COUNT(fl.user_id)                                           AS confirmed_fraud_accounts
    FROM users u
    LEFT JOIN first_dep fd    ON fd.user_id = u.user_id
    LEFT JOIN fraud_labels fl ON fl.user_id = u.user_id
    GROUP BY week_start ORDER BY week_start""", con)
signup_weekly["deposit_conversion_pct"] = 100 * signup_weekly.depositors / signup_weekly.signups
signup_weekly["fraud_account_rate_pct"] = 100 * signup_weekly.confirmed_fraud_accounts / signup_weekly.signups

pay_weekly = pd.read_sql_query("""
    SELECT STRFTIME('%Y-%m-%d', DATE(deposit_ts, 'weekday 0', '-6 days')) AS week_start,
           COUNT(*)                                                       AS deposit_attempts,
           SUM(status = 'declined')                                       AS declined,
           SUM(CASE WHEN status IN ('success','chargeback') THEN amount ELSE 0 END) AS deposit_dollars,
           SUM(CASE WHEN status = 'chargeback' THEN amount ELSE 0 END)    AS chargeback_dollars
    FROM deposits GROUP BY week_start ORDER BY week_start""", con)
pay_weekly["decline_rate_pct"] = 100 * pay_weekly.declined / pay_weekly.deposit_attempts
pay_weekly["chargeback_rate_pct"] = 100 * pay_weekly.chargeback_dollars / pay_weekly.deposit_dollars
weekly = signup_weekly.merge(pay_weekly, on="week_start", how="outer").sort_values("week_start")
weekly["cohort_mature"] = weekly.week_start <= MATURE_BEFORE
weekly.round(2).to_csv(here / "weekly_kpis.csv", index=False)

bonus = pd.read_sql_query("""
    SELECT SUM(bonus_amount) AS total_bonus,
           SUM(CASE WHEN fl.user_id IS NOT NULL THEN bonus_amount ELSE 0 END) AS bonus_to_fraud
    FROM promo_claims pc LEFT JOIN fraud_labels fl ON fl.user_id = pc.user_id""", con).iloc[0]

# ------------------------------------------------------------- data quality checks
hourly = pd.read_sql_query("""
    SELECT STRFTIME('%Y-%m-%d %H:00:00', deposit_ts) AS hour, COUNT(*) AS n
    FROM deposits GROUP BY hour ORDER BY hour""", con)
hourly["hour"] = pd.to_datetime(hourly.hour)
full = pd.date_range(hourly.hour.min(), hourly.hour.max(), freq="h")
hourly = hourly.set_index("hour").reindex(full, fill_value=0).rename_axis("hour").reset_index()
hourly["hod"] = hourly.hour.dt.hour
# baseline = median of the same hour-of-day over the previous 14 days
hourly["baseline"] = (hourly.groupby("hod")["n"]
                      .transform(lambda s: s.shift(1).rolling(14, min_periods=7).median()))
hourly["ratio"] = hourly.n / hourly.baseline
low = hourly[(hourly.baseline >= 8) & (hourly.ratio <= 0.35)]
# group consecutive anomalous hours into incidents
incidents = []
if len(low):
    grp = (low.hour.diff() != pd.Timedelta(hours=1)).cumsum()
    for _, g in low.groupby(grp):
        if len(g) < 3:            # single low hours are normal noise; real outages last several hours
            continue
        incidents.append({"type": "volume drop (possible logging outage)",
                          "start": g.hour.min(), "end": g.hour.max() + pd.Timedelta(hours=1),
                          "hours": len(g), "detail": f"{int(g.n.sum())} deposits vs ~{int(g.baseline.sum())} expected"})

daily = pd.read_sql_query("""
    SELECT DATE(deposit_ts) AS day, COUNT(*) AS rows_logged,
           COUNT(*) - COUNT(DISTINCT user_id || '|' || deposit_ts || '|' || amount) AS duplicate_rows
    FROM deposits GROUP BY day ORDER BY day""", con)
daily["duplicate_rate_pct"] = 100 * daily.duplicate_rows / daily.rows_logged
daily.round(3).to_csv(here / "daily_data_quality.csv", index=False)
for _, r in daily[daily.duplicate_rate_pct > 1.0].iterrows():
    incidents.append({"type": "duplicate events", "start": pd.Timestamp(r.day), "end": pd.Timestamp(r.day) + pd.Timedelta(days=1),
                      "hours": 24, "detail": f"{int(r.duplicate_rows)} duplicate deposit rows ({r.duplicate_rate_pct:.1f}% of that day)"})
inc = pd.DataFrame(incidents)
inc.to_csv(here / "data_quality_incidents.csv", index=False)
print(inc.to_string(index=False))


# ------------------------------------------------------------- charts
def fig_to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def style(ax, title, ylabel):
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(axis="y", alpha=0.25)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    ax.tick_params(labelsize=8)


x = pd.to_datetime(weekly.week_start)
charts = {}

fig, ax = plt.subplots(figsize=(7, 3))
ax.bar(x, weekly.signups, width=5, color="#9bb7d4")
style(ax, "Weekly signups", "signups")
ax2 = ax.twinx()
ax2.plot(x, weekly.fraud_account_rate_pct, color="#d9480f", lw=2)
ax2.set_ylabel("confirmed fraud accounts (% of signups)", fontsize=8, color="#d9480f")
ax2.tick_params(labelsize=8, colors="#d9480f")
ax2.spines["top"].set_visible(False)
charts["signups"] = fig_to_b64(fig)

fig, ax = plt.subplots(figsize=(7, 3))
m = weekly[weekly.cohort_mature]
ax.plot(pd.to_datetime(m.week_start), m.chargeback_rate_pct, color="#d9480f", lw=2, label="chargeback rate (% of deposit $)")
style(ax, "Chargeback rate by deposit week (mature cohorts only)", "% of deposit dollars")
ax.set_ylim(bottom=0)
ax.legend(frameon=False, fontsize=8)
charts["chargeback"] = fig_to_b64(fig)

fig, ax = plt.subplots(figsize=(7, 3))
ok = weekly.deposit_conversion_pct.notna()
ax.plot(x[ok], weekly.deposit_conversion_pct[ok], color="#2b8a3e", lw=2)
style(ax, "Conversion and payment health", "signup to first deposit %")
ax.set_ylim(0, 100)
ax2 = ax.twinx()
d = weekly[weekly.deposit_attempts > 200]
ax2.plot(pd.to_datetime(d.week_start), d.decline_rate_pct, color="#7b8794", lw=2, ls="--")
ax2.set_ylabel("payment decline rate % (dashed)", fontsize=8, color="#7b8794")
ax2.set_ylim(0, 10)
ax2.tick_params(labelsize=8, colors="#7b8794")
ax2.spines["top"].set_visible(False)
charts["conversion"] = fig_to_b64(fig)

# outage zoom
if len(inc[inc.type.str.startswith("volume")]):
    t0 = inc[inc.type.str.startswith("volume")].start.min()
    z = hourly[(hourly.hour >= t0 - pd.Timedelta(days=2)) & (hourly.hour <= t0 + pd.Timedelta(days=2))]
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.plot(z.hour, z.n, color="#364fc7", lw=1.6, label="deposits per hour")
    ax.plot(z.hour, z.baseline, color="#868e96", lw=1.2, ls="--", label="expected (14-day same-hour median)")
    style(ax, "Anomaly: deposit volume collapse", "deposits / hour")
    ax.legend(frameon=False, fontsize=8)
    fig.autofmt_xdate()
    charts["outage"] = fig_to_b64(fig)

fig, ax = plt.subplots(figsize=(7, 3))
ax.plot(pd.to_datetime(daily.day), daily.duplicate_rate_pct, color="#c92a2a", lw=1.5)
style(ax, "Anomaly: duplicate deposit events", "% duplicate rows")
charts["dup"] = fig_to_b64(fig)

# ------------------------------------------------------------- html
last_mature = weekly[weekly.cohort_mature].tail(8)
tiles = [
    ("Signups", f"{int(signup_weekly.signups.sum()):,}"),
    ("Signup to deposit", f"{100*signup_weekly.depositors.sum()/signup_weekly.signups.sum():.1f}%"),
    ("Confirmed fraud accounts", f"{100*signup_weekly.confirmed_fraud_accounts.sum()/signup_weekly.signups.sum():.2f}%"),
    ("Chargebacks (known so far)", f"${pay_weekly.chargeback_dollars.sum():,.0f}"),
    ("Bonus $ paid to fraud", f"{100*bonus.bonus_to_fraud/bonus.total_bonus:.1f}%"),
]
tile_html = "".join(f'<div class="tile"><div class="v">{v}</div><div class="k">{k}</div></div>' for k, v in tiles)
inc_rows = "".join(
    f"<tr><td>{r.type}</td><td>{r.start:%Y-%m-%d %H:%M}</td><td>{r.detail}</td></tr>" for r in inc.itertuples())
html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Fraud and payments dashboard (synthetic data)</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1f2933}}
.wrap{{max-width:860px;margin:0 auto;padding:20px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#667085;font-size:13px;margin-bottom:16px}}
.tiles{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}}
.tile{{background:#fff;border-radius:10px;padding:12px 14px;flex:1 1 140px;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
.tile .v{{font-size:22px;font-weight:700}} .tile .k{{font-size:12px;color:#667085}}
.card{{background:#fff;border-radius:10px;padding:12px;margin-bottom:14px;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
.card img{{width:100%}} .note{{font-size:12px;color:#667085;margin:4px 2px}}
table{{width:100%;border-collapse:collapse;font-size:13px}} td,th{{border-bottom:1px solid #eceff3;padding:6px;text-align:left}}
.banner{{background:#fff4e6;border:1px solid #ffd8a8;border-radius:8px;padding:8px 12px;font-size:12px;margin-bottom:14px}}
</style></head><body><div class="wrap">
<h1>Fraud and payments dashboard</h1>
<div class="sub">Synthetic data (simulated fantasy-sports-style platform). Jan to Sep 2026.</div>
<div class="banner">All numbers come from simulated data built for practice. They are not real company figures.</div>
<div class="tiles">{tile_html}</div>
<div class="card"><img src="data:image/png;base64,{charts['signups']}"><div class="note">Fraud accounts are labels confirmed by review days after signup, so recent weeks are understated.</div></div>
<div class="card"><img src="data:image/png;base64,{charts['chargeback']}"><div class="note">Chargebacks arrive 7 to 30 days after the deposit. Cohorts after {MATURE_BEFORE} are hidden because they are incomplete.</div></div>
<div class="card"><img src="data:image/png;base64,{charts['conversion']}"></div>
<h2 style="font-size:16px">Data quality: anomalies to triage with Engineering</h2>
<div class="card"><img src="data:image/png;base64,{charts.get('outage','')}"></div>
<div class="card"><img src="data:image/png;base64,{charts['dup']}"></div>
<div class="card"><table><tr><th>Type</th><th>Start</th><th>Detail</th></tr>{inc_rows}</table>
<div class="note">Questions I would ask: did a deploy, queue, or logging job fail at that time? Are the missing events recoverable from the payment processor? Should metrics for that window be excluded or backfilled?</div></div>
</div></body></html>"""
(here / "dashboard.html").write_text(html)
print("wrote dashboard.html, weekly_kpis.csv, daily_data_quality.csv, data_quality_incidents.csv")
