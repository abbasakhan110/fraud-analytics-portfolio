"""
PROJECT 2: Fraud vs. friction rule backtest (synthetic data).

Business question: a rule that blocks more fraud also blocks more real players.
Where is the best tradeoff, and does it hold up on data the rule never saw?

Method
  1. Build point-in-time features in SQL (only information available at decision time).
  2. Split by signup date: TRAIN = before 2026-06-01, HOLDOUT = 2026-06-01 and later.
  3. Sweep candidate rules on TRAIN, pick the best net benefit.
  4. Score the chosen rule on HOLDOUT and report uncertainty (Wilson CIs + bootstrap).
  5. Sensitivity: how does the answer change if our friction-cost assumptions are wrong?

ASSUMPTIONS (editable below) are guesses, not facts about any real company.
Usage: python3 backtest.py
"""
import sqlite3
import itertools
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

here = Path(__file__).parent
con = sqlite3.connect(here.parent / "data" / "fraud.db")

# ---------------------------- assumptions ----------------------------------
SPLIT_DATE = "2026-06-01"
CHARGEBACK_FEE = 15.0        # $ fee per chargeback on top of the refunded amount
FRICTION_CHURN = 0.25        # share of flagged legit users who give up because of the hold
LEGIT_VALUE = 40.0           # $ expected net value of a legit new user (what we lose if they churn)
REVIEW_COST = 2.0            # $ analyst time per flagged account
RNG = np.random.default_rng(7)

# ---------------------------- 1. features in SQL ---------------------------
FEATURE_SQL = """
WITH attempts AS (                       -- every deposit attempt, ranked per user
    SELECT d.user_id, d.amount, d.status, d.deposit_ts,
           ROW_NUMBER() OVER (PARTITION BY d.user_id ORDER BY d.deposit_ts) AS rn
    FROM deposits d
),
first_attempt AS (
    SELECT a.user_id,
           a.amount AS first_amount,
           (julianday(a.deposit_ts) - julianday(u.signup_ts)) * 1440 AS minutes_to_first_attempt
    FROM attempts a JOIN users u ON u.user_id = a.user_id
    WHERE a.rn = 1
),
early_declines AS (                      -- declines in the first 3 hours after signup
    SELECT d.user_id, COUNT(*) AS declines_3h
    FROM deposits d JOIN users u ON u.user_id = d.user_id
    WHERE d.status = 'declined'
      AND (julianday(d.deposit_ts) - julianday(u.signup_ts)) * 24 <= 3
    GROUP BY d.user_id
),
dev AS (                                 -- POINT-IN-TIME: accounts that signed up BEFORE this one on the same device
    SELECT user_id,
           COUNT(*) OVER (PARTITION BY device_id ORDER BY signup_ts, user_id
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_on_device
    FROM users
),
loss AS (                                -- what each account actually cost us
    SELECT u.user_id,
           COALESCE((SELECT SUM(amount + :fee) FROM deposits d
                     WHERE d.user_id = u.user_id AND d.status = 'chargeback'), 0)
         + COALESCE((SELECT SUM(bonus_amount) FROM promo_claims p
                     WHERE p.user_id = u.user_id), 0) AS cost_if_fraud
    FROM users u
)
SELECT u.user_id, u.signup_ts, u.email_domain,
       fa.first_amount, fa.minutes_to_first_attempt,
       COALESCE(ed.declines_3h, 0)  AS declines_3h,
       dv.prior_on_device,
       l.cost_if_fraud,
       CASE WHEN fl.user_id IS NULL THEN 0 ELSE 1 END AS is_fraud
FROM users u
LEFT JOIN first_attempt  fa ON fa.user_id = u.user_id
LEFT JOIN early_declines ed ON ed.user_id = u.user_id
JOIN      dev dv            ON dv.user_id = u.user_id
JOIN      loss l            ON l.user_id  = u.user_id
LEFT JOIN fraud_labels   fl ON fl.user_id = u.user_id
"""
df = pd.read_sql_query(FEATURE_SQL, con, params={"fee": CHARGEBACK_FEE})
df["first_amount"] = df["first_amount"].fillna(0)
df["minutes_to_first_attempt"] = df["minutes_to_first_attempt"].fillna(1e9)
df["disposable_email"] = df.email_domain.isin(["tempmail.io", "mailnesia.com"]).astype(int)
# only fraud accounts have a real "cost if fraud"; for legit users cost is irrelevant to loss prevented
df["fraud_cost"] = np.where(df.is_fraud == 1, df.cost_if_fraud, 0.0)

train = df[df.signup_ts < SPLIT_DATE].copy()
hold = df[df.signup_ts >= SPLIT_DATE].copy()
print(f"train accounts: {len(train):,} | holdout accounts: {len(hold):,}")


# ---------------------------- 2. rule + scoring ----------------------------
def apply_rule(d, amount_t, device_k, use_disposable):
    flag = (d.first_amount >= amount_t) | (d.prior_on_device >= device_k)
    if use_disposable:
        flag = flag | ((d.disposable_email == 1) & (d.minutes_to_first_attempt <= 180) & (d.declines_3h >= 1))
    return flag


def score(d, flag, legit_value=LEGIT_VALUE):
    fraud = d.is_fraud == 1
    legit = ~fraud
    tp, fp = int((flag & fraud).sum()), int((flag & legit).sum())
    prevented = float(d.loc[flag & fraud, "fraud_cost"].sum())
    total_loss = float(d.loc[fraud, "fraud_cost"].sum())
    friction = fp * FRICTION_CHURN * legit_value
    review = int(flag.sum()) * REVIEW_COST
    return {
        "flagged": int(flag.sum()), "fraud_caught": tp, "legit_flagged": fp,
        "fraud_catch_rate": tp / max(int(fraud.sum()), 1),
        "precision": tp / max(int(flag.sum()), 1),
        "legit_friction_rate": fp / max(int(legit.sum()), 1),
        "loss_prevented": prevented, "pct_loss_prevented": prevented / total_loss if total_loss else 0,
        "friction_cost": friction, "review_cost": review,
        "net_benefit": prevented - friction - review,
    }


AMOUNT_GRID = [75, 100, 125, 150, 200, 250, 300]
DEVICE_GRID = [1, 2, 3, 4]
rows = []
for a, k, dsp in itertools.product(AMOUNT_GRID, DEVICE_GRID, [False, True]):
    s = score(train, apply_rule(train, a, k, dsp))
    rows.append({"amount_t": a, "device_k": k, "disposable_rule": dsp, **s})
grid = pd.DataFrame(rows).sort_values("net_benefit", ascending=False)
best = grid.iloc[0]
A, K, DSP = int(best.amount_t), int(best.device_k), bool(best.disposable_rule)
print("\nBest rule on TRAIN:", dict(amount_t=A, device_k=K, disposable_rule=DSP))

# ---------------------------- 3. holdout -----------------------------------
base_train = score(train, apply_rule(train, A, K, DSP))
base_hold = score(hold, apply_rule(hold, A, K, DSP))
no_rule_loss = float(hold.fraud_cost.sum())
print("train:", {k: round(v, 3) if isinstance(v, float) else v for k, v in base_train.items()})
print("holdout:", {k: round(v, 3) if isinstance(v, float) else v for k, v in base_hold.items()})


def wilson(k, n, z=1.96):
    if n == 0:
        return (0, 0)
    p = k / n
    den = 1 + z**2 / n
    c = p + z**2 / (2 * n)
    m = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return ((c - m) / den, (c + m) / den)


n_fraud_h = int((hold.is_fraud == 1).sum())
n_legit_h = int((hold.is_fraud == 0).sum())
catch_ci = wilson(base_hold["fraud_caught"], n_fraud_h)
fric_ci = wilson(base_hold["legit_flagged"], n_legit_h)

# bootstrap CI on holdout net benefit
flag_h = apply_rule(hold, A, K, DSP).values
boots = []
for _ in range(500):
    idx = RNG.integers(0, len(hold), len(hold))
    s = score(hold.iloc[idx].reset_index(drop=True), pd.Series(flag_h[idx]))
    boots.append(s["net_benefit"])
net_ci = (np.percentile(boots, 2.5), np.percentile(boots, 97.5))

# ---------------------------- 4. sensitivity -------------------------------
sens = []
for lv in [10, 20, 40, 80, 160]:
    best_lv = None
    for a, k, dsp in itertools.product(AMOUNT_GRID, DEVICE_GRID, [False, True]):
        s = score(train, apply_rule(train, a, k, dsp), legit_value=lv)
        if best_lv is None or s["net_benefit"] > best_lv[0]:
            best_lv = (s["net_benefit"], a, k, dsp)
    h = score(hold, apply_rule(hold, best_lv[1], best_lv[2], best_lv[3]), legit_value=lv)
    sens.append({"legit_user_value_$": lv, "best_amount_t": best_lv[1], "best_device_k": best_lv[2],
                 "disposable_rule": best_lv[3], "holdout_fraud_catch": round(h["fraud_catch_rate"], 3),
                 "holdout_legit_friction": round(h["legit_friction_rate"], 4),
                 "holdout_net_benefit_$": round(h["net_benefit"])})
sens = pd.DataFrame(sens)

# per-rule contribution on holdout (what does each piece add?)
parts = []
for label, flag in [
    ("amount rule only", hold.first_amount >= A),
    ("shared-device rule only", hold.prior_on_device >= K),
    ("disposable-email + early decline rule only",
     (hold.disposable_email == 1) & (hold.minutes_to_first_attempt <= 180) & (hold.declines_3h >= 1)),
    ("combined (chosen rule)", pd.Series(flag_h, index=hold.index)),
]:
    s = score(hold, flag)
    parts.append({"rule": label, "fraud_catch_%": round(100 * s["fraud_catch_rate"], 1),
                  "legit_flagged_%": round(100 * s["legit_friction_rate"], 2),
                  "precision_%": round(100 * s["precision"], 1), "net_benefit_$": round(s["net_benefit"])})
parts = pd.DataFrame(parts)

# ---------------------------- 5. chart + report ----------------------------
fig, ax = plt.subplots(figsize=(7.5, 4.6))
tr = grid.copy()
ax.scatter(100 * tr.legit_friction_rate, 100 * tr.pct_loss_prevented, s=22, alpha=0.55, color="#7b8794", label="candidate rules (train)")
ax.scatter(100 * base_train["legit_friction_rate"], 100 * base_train["pct_loss_prevented"], s=120, color="#d9480f", zorder=5, label="chosen rule (train)")
ax.scatter(100 * base_hold["legit_friction_rate"], 100 * base_hold["pct_loss_prevented"], s=120, marker="D", color="#1c7ed6", zorder=5, label="chosen rule (holdout)")
ax.set_xscale("symlog", linthresh=0.5)
ax.set_xlim(-0.05, 30)
ax.set_xlabel("% of legitimate new users flagged (friction, log-ish scale)")
ax.set_ylabel("% of fraud $ loss prevented")
ax.set_title("Fraud vs. friction: every rule is a tradeoff")
ax.grid(alpha=0.25)
ax.legend(frameon=False, fontsize=8)
fig.tight_layout()
fig.savefig(here / "tradeoff_chart.png", dpi=160)

md = []
md.append("# Project 2 results: fraud vs. friction backtest (auto-generated)\n")
md.append(f"Split: TRAIN = signups before {SPLIT_DATE} ({len(train):,} accounts), HOLDOUT = {SPLIT_DATE} and later ({len(hold):,} accounts).\n")
md.append(f"Assumptions: chargeback fee ${CHARGEBACK_FEE:.0f}; {int(FRICTION_CHURN*100)}% of flagged legit users churn; legit-user value ${LEGIT_VALUE:.0f}; review cost ${REVIEW_COST:.0f}/flag. (Guesses, not facts.)\n")
md.append(f"## Chosen rule (picked on TRAIN only)\n\nFlag if first deposit >= **${A}** OR **{K}+ earlier accounts** already on the same device"
          + (" OR (disposable email AND deposit within 3h AND 1+ early decline)." if DSP else ".") + "\n")
md.append("## Holdout performance (data the rule never saw)\n")
md.append(f"- Fraud accounts caught: **{100*base_hold['fraud_catch_rate']:.1f}%** (95% CI {100*catch_ci[0]:.1f}% to {100*catch_ci[1]:.1f}%)\n"
          f"- Fraud $ loss prevented: **{100*base_hold['pct_loss_prevented']:.1f}%** (${base_hold['loss_prevented']:,.0f} of ${no_rule_loss:,.0f})\n"
          f"- Legit users flagged: **{100*base_hold['legit_friction_rate']:.2f}%** (95% CI {100*fric_ci[0]:.2f}% to {100*fric_ci[1]:.2f}%) = {base_hold['legit_flagged']:,} people\n"
          f"- Precision: {100*base_hold['precision']:.1f}%\n"
          f"- Net benefit: **${base_hold['net_benefit']:,.0f}** (bootstrap 95% CI ${net_ci[0]:,.0f} to ${net_ci[1]:,.0f})\n")
md.append("## What each piece of the rule contributes (holdout)\n\n" + parts.to_markdown(index=False) + "\n")
md.append("## Sensitivity: what if our 'legit user value' assumption is wrong?\n\n" + sens.to_markdown(index=False) + "\n")
md.append("## Top 10 candidate rules on TRAIN\n\n" + grid.head(10).round(4).to_markdown(index=False) + "\n")
(here / "results.md").write_text("\n".join(md))
grid.to_csv(here / "rule_grid_train.csv", index=False)
print("\n".join(md))
