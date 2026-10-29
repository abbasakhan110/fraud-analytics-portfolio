"""
Generate a SYNTHETIC fantasy-sports-style fraud dataset (SQLite).

IMPORTANT: this data is simulated. It is NOT real PrizePicks (or any company's) data.
It is designed to look like an online transactional platform so the analysis
skills (SQL, metrics, backtesting) are the same ones used on real data.

Three kinds of accounts are simulated:
  - legit        : normal players (the vast majority)
  - promo_ring   : multi-accounting / bonus abuse (rings sharing devices / IPs)
  - stolen_card  : new accounts making big deposits with stolen cards -> chargebacks

Tables written to fraud.db:
  users, deposits, promo_claims, entries, withdrawals, fraud_labels
Run:  python3 generate_data.py
"""
import sqlite3
import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)

START = pd.Timestamp("2026-01-01")
SIGNUP_END = pd.Timestamp("2026-08-31")
CUTOFF = pd.Timestamp("2026-09-30")          # data "as of" date
SIGNUP_SECONDS = int((SIGNUP_END - START).total_seconds())
CUTOFF_SECONDS = int((CUTOFF - START).total_seconds())

N_LEGIT = 58_000
N_STOLEN = 450
RING_SIZES = rng.integers(3, 9, size=140)    # 140 rings of 3-8 accounts (the last 40 are a promo-abuse spike)
STATES = ["IL", "GA", "TX", "FL", "CA", "NY", "OH", "PA", "NC", "MI"]
LEGIT_DOMAINS = ["gmail.com", "yahoo.com", "icloud.com", "outlook.com", "hotmail.com", "proton.me",
                 "tempmail.io", "mailnesia.com"]            # a few real people use disposable email too
LEGIT_DOM_P = [0.585, 0.12, 0.12, 0.10, 0.04, 0.02, 0.010, 0.005]
BAD_DOMAINS = ["tempmail.io", "mailnesia.com", "gmail.com", "outlook.com", "yahoo.com", "icloud.com"]
BAD_DOM_P = [0.30, 0.15, 0.30, 0.12, 0.08, 0.05]
AMOUNTS = np.array([10, 20, 25, 50, 100])
AMOUNT_P = np.array([0.15, 0.25, 0.20, 0.25, 0.15])
METHODS = ["card", "paypal", "apple_pay", "bank"]
METHOD_P = [0.60, 0.25, 0.10, 0.05]


def ts(seconds):
    return (START + pd.to_timedelta(np.asarray(seconds), unit="s")).strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------------
# 1. USERS
# ----------------------------------------------------------------------------
users = []

# --- legit users ---
signup = (SIGNUP_SECONDS * rng.beta(1.3, 1.0, N_LEGIT)).astype(int)   # growth toward football season
device = np.array([f"dev_L{i}" for i in range(N_LEGIT)], dtype=object)
share = rng.random(N_LEGIT) < 0.03                                   # households sharing a phone/tablet
for i in np.where(share)[0]:
    if i > 0:
        device[i] = device[rng.integers(0, i)]
ip_pool = 45_000
ip = np.array([f"ip_{k}" for k in rng.integers(0, ip_pool, N_LEGIT)], dtype=object)
legit = pd.DataFrame({
    "signup_s": signup,
    "device_id": device,
    "ip_hash": ip,
    "email_domain": rng.choice(LEGIT_DOMAINS, N_LEGIT, p=LEGIT_DOM_P),
    "state": rng.choice(STATES, N_LEGIT),
    "fraud_type": "legit",
    "ring_id": -1,
})
users.append(legit)

# --- promo rings (multi-accounting) ---
ring_rows = []
for r, size in enumerate(RING_SIZES):
    if r >= 100:     # spike: 40 rings appear in a two-week window (Jul 20 - Aug 3) after a promo push
        ring_start = int(rng.integers(200 * 86400, 214 * 86400))
    else:
        ring_start = int((SIGNUP_SECONDS - 4 * 86400) * rng.beta(1.3, 1.0))
    ring_dev = f"dev_R{r}"
    ring_ip = f"ip_R{r}"
    for j in range(size):
        ring_rows.append({
            "signup_s": ring_start + int(rng.integers(0, 3 * 86400)),
            "device_id": ring_dev if rng.random() < 0.85 else f"dev_Rx{r}_{j}",
            "ip_hash": ring_ip if rng.random() < 0.70 else f"ip_{rng.integers(0, ip_pool)}",
            "email_domain": rng.choice(BAD_DOMAINS, p=BAD_DOM_P),
            "state": rng.choice(STATES),
            "fraud_type": "promo_ring",
            "ring_id": r,
        })
users.append(pd.DataFrame(ring_rows))

# --- stolen-card accounts ---
proxy_ips = [f"ip_P{k}" for k in range(60)]
users.append(pd.DataFrame({
    "signup_s": (SIGNUP_SECONDS * rng.beta(1.3, 1.0, N_STOLEN)).astype(int),
    "device_id": [f"dev_S{i}" for i in range(N_STOLEN)],
    "ip_hash": rng.choice(proxy_ips, N_STOLEN),
    "email_domain": rng.choice(BAD_DOMAINS, N_STOLEN, p=BAD_DOM_P),
    "state": rng.choice(STATES, N_STOLEN),
    "fraud_type": "stolen_card",
    "ring_id": -1,
}))

u = pd.concat(users, ignore_index=True)
u = u.sort_values("signup_s").reset_index(drop=True)
u["user_id"] = np.arange(1, len(u) + 1)
u["signup_ts"] = ts(u["signup_s"])
N = len(u)

# ----------------------------------------------------------------------------
# 2. DEPOSITS
# ----------------------------------------------------------------------------
dep_rows = []   # list of DataFrames


def mk_deposits(user_ids, times_s, amounts, decline_p, chargeback_p):
    n = len(user_ids)
    declined = rng.random(n) < decline_p
    status = np.where(declined, "declined", "success").astype(object)
    cb = (~declined) & (rng.random(n) < chargeback_p)
    cb_delay = rng.integers(7 * 86400, 30 * 86400, n)
    cb_s = np.asarray(times_s) + cb_delay
    cb &= cb_s <= CUTOFF_SECONDS             # chargebacks arrive late; recent ones are still unknown
    status[cb] = "chargeback"
    cb_ts = np.where(cb, ts(np.minimum(cb_s, CUTOFF_SECONDS)), None)
    return pd.DataFrame({
        "user_id": user_ids,
        "deposit_s": np.asarray(times_s),
        "amount": amounts,
        "method": rng.choice(METHODS, n, p=METHOD_P),
        "status": status,
        "chargeback_ts": cb_ts,
    })


# legit: 88% deposit; first deposit ~20h after signup (exponential), then a few more
L = u[u.fraud_type == "legit"]
has_first = rng.random(len(L)) < 0.88
Lf = L[has_first]
first_s = Lf.signup_s.values + rng.exponential(20 * 3600, len(Lf)).astype(int)
first_s = np.minimum(first_s, CUTOFF_SECONDS - 60)
dep_rows.append(mk_deposits(Lf.user_id.values, first_s, rng.choice(AMOUNTS, len(Lf), p=AMOUNT_P), 0.035, 0.0015))
activity = rng.gamma(2.0, 0.5, len(Lf))
k = rng.poisson(2.0 * activity)
rep_u = np.repeat(Lf.user_id.values, k)
rep_first = np.repeat(first_s, k)
extra_s = rep_first + (rng.random(len(rep_u)) * (CUTOFF_SECONDS - rep_first)).astype(int)
dep_rows.append(mk_deposits(rep_u, extra_s, rng.choice(AMOUNTS, len(rep_u), p=AMOUNT_P), 0.035, 0.0015))

# promo ring: one clean deposit that just qualifies for the match bonus ($20-$50)
R = u[u.fraud_type == "promo_ring"]
ring_first = R.signup_s.values + rng.integers(600, 3 * 86400, len(R))
dep_rows.append(mk_deposits(R.user_id.values, ring_first, rng.choice([20, 25, 50], len(R), p=[0.4, 0.4, 0.2]), 0.02, 0.0))

# stolen card: 2-6 attempts within a few hours of signup, large amounts, lots of declines, mostly chargebacks
S = u[u.fraud_type == "stolen_card"]
att = rng.integers(2, 7, len(S))
s_u = np.repeat(S.user_id.values, att)
s_sign = np.repeat(S.signup_s.values, att)
s_s = s_sign + np.where(rng.random(len(s_u)) < 0.25, rng.integers(3 * 3600, 30 * 3600, len(s_u)),
                        rng.integers(300, 3 * 3600, len(s_u)))
s_amt = (np.round(rng.lognormal(np.log(150), 0.5, len(s_u)) / 5) * 5).clip(25, 1000)
s_amt = np.where(rng.random(len(s_u)) < 0.20, rng.choice([5, 10, 15], len(s_u)), s_amt)   # card testing
dep_rows.append(mk_deposits(s_u, s_s, s_amt, 0.40, 0.75))

deposits = pd.concat(dep_rows, ignore_index=True).sort_values("deposit_s").reset_index(drop=True)

# --- injected data-quality incidents (so there is something to triage with Engineering) ---
OUT_START = int((pd.Timestamp("2026-06-10 02:00") - START).total_seconds())
OUT_END = int((pd.Timestamp("2026-06-10 14:00") - START).total_seconds())
in_outage = deposits.deposit_s.between(OUT_START, OUT_END) & (rng.random(len(deposits)) < 0.90)
deposits = deposits[~in_outage]                                   # incident 1: events lost during a logging outage
DUP_START = int((pd.Timestamp("2026-07-22") - START).total_seconds())
dup_mask = deposits.deposit_s.between(DUP_START, DUP_START + 86400) & (rng.random(len(deposits)) < 0.5)
deposits = pd.concat([deposits, deposits[dup_mask]], ignore_index=True)   # incident 2: duplicate events after a deploy
deposits = deposits.sort_values("deposit_s", kind="stable").reset_index(drop=True)
deposits["deposit_id"] = np.arange(1, len(deposits) + 1)
deposits["deposit_ts"] = ts(deposits.deposit_s)
deposits = deposits[["deposit_id", "user_id", "deposit_ts", "amount", "method", "status", "chargeback_ts"]]

# ----------------------------------------------------------------------------
# 3. PROMO CLAIMS  (deposit-match bonus: first successful deposit >= $20, matched up to $50)
# ----------------------------------------------------------------------------
dd = deposits[deposits.status.isin(["success", "chargeback"])].copy()
first_dep = dd.sort_values("deposit_ts").groupby("user_id").first().reset_index()
first_dep = first_dep.merge(u[["user_id", "fraud_type"]], on="user_id")
elig = first_dep[first_dep.amount >= 20]
claim_p = np.where(elig.fraud_type == "promo_ring", 1.0,
                   np.where(elig.fraud_type == "stolen_card", 0.30, 0.55))
claimed = elig[rng.random(len(elig)) < claim_p]
promo_claims = pd.DataFrame({
    "user_id": claimed.user_id.values,
    "promo_code": "DEPOSIT_MATCH",
    "claimed_ts": claimed.deposit_ts.values,
    "bonus_amount": np.minimum(claimed.amount.values, 50),
})
promo_claims.insert(0, "claim_id", np.arange(1, len(promo_claims) + 1))

# ----------------------------------------------------------------------------
# 4. ENTRIES (contest entries)
# ----------------------------------------------------------------------------
fd = first_dep.set_index("user_id")
ent_users, ent_start = [], []
for ftype, lam in [("legit", 12), ("promo_ring", 1.5), ("stolen_card", 0.6)]:
    sub = fd[fd.fraud_type == ftype]
    act = rng.gamma(2.0, 0.5, len(sub)) if ftype == "legit" else np.ones(len(sub))
    cnt = rng.poisson(lam * act)
    ent_users.append(np.repeat(sub.index.values, cnt))
    ent_start.append(np.repeat((pd.to_datetime(sub.deposit_ts) - START).dt.total_seconds().astype(int).values, cnt))
e_u = np.concatenate(ent_users)
e_start = np.concatenate(ent_start)
e_s = e_start + (rng.random(len(e_u)) * np.maximum(CUTOFF_SECONDS - e_start, 1)).astype(int)
fee = rng.choice([1, 5, 10, 20], len(e_u), p=[0.3, 0.35, 0.25, 0.1])
win = rng.random(len(e_u)) < 0.5
entries = pd.DataFrame({
    "user_id": e_u,
    "entry_ts": ts(e_s),
    "sport": rng.choice(["NFL", "NBA", "MLB", "NHL", "CS2", "LoL"], len(e_u), p=[.35, .3, .15, .08, .07, .05]),
    "entry_fee": fee,
    "payout": np.where(win, fee * 1.8, 0.0).round(2),
})
entries = entries.sort_values("entry_ts").reset_index(drop=True)
entries.insert(0, "entry_id", np.arange(1, len(entries) + 1))

# ----------------------------------------------------------------------------
# 5. WITHDRAWALS
# ----------------------------------------------------------------------------
w_rows = []
net = entries.groupby("user_id").payout.sum() - entries.groupby("user_id").entry_fee.sum()
leg_w = fd[(fd.fraud_type == "legit")]
pick = leg_w[rng.random(len(leg_w)) < 0.18]
w_rows.append(pd.DataFrame({
    "user_id": pick.index.values,
    "requested_ts": ts((pd.to_datetime(pick.deposit_ts) - START).dt.total_seconds().astype(int).values
                       + rng.integers(2 * 86400, 60 * 86400, len(pick))),
    "amount": rng.choice([20, 50, 100, 200], len(pick)),
}))
rg = fd[fd.fraud_type == "promo_ring"]
rg = rg[rng.random(len(rg)) < 0.90]
rg_bonus = promo_claims.set_index("user_id").bonus_amount.reindex(rg.index).fillna(0).values
w_rows.append(pd.DataFrame({
    "user_id": rg.index.values,
    "requested_ts": ts((pd.to_datetime(rg.deposit_ts) - START).dt.total_seconds().astype(int).values
                       + rng.integers(86400, 3 * 86400, len(rg))),
    "amount": (rg.amount.values + rg_bonus * 0.8).round(2),
}))
withdrawals = pd.concat(w_rows, ignore_index=True).sort_values("requested_ts").reset_index(drop=True)
withdrawals = withdrawals[withdrawals.requested_ts <= CUTOFF.strftime("%Y-%m-%d 23:59:59")]
withdrawals.insert(0, "withdrawal_id", np.arange(1, len(withdrawals) + 1))

# ----------------------------------------------------------------------------
# 6. FRAUD LABELS (what manual review confirmed, days after signup)
# ----------------------------------------------------------------------------
bad = u[u.fraud_type != "legit"]
confirmed = bad[rng.random(len(bad)) < 0.92]      # review catches ~92% of the true fraud eventually
fraud_labels = pd.DataFrame({
    "user_id": confirmed.user_id.values,
    "fraud_type": confirmed.fraud_type.values,
    "confirmed_ts": ts(confirmed.signup_s.values + rng.integers(5 * 86400, 20 * 86400, len(confirmed))),
})

# ----------------------------------------------------------------------------
# WRITE TO SQLITE
# ----------------------------------------------------------------------------
users_out = u[["user_id", "signup_ts", "state", "email_domain", "device_id", "ip_hash"]]
con = sqlite3.connect("fraud.db")
for name, df in [("users", users_out), ("deposits", deposits), ("promo_claims", promo_claims),
                 ("entries", entries), ("withdrawals", withdrawals), ("fraud_labels", fraud_labels)]:
    df.to_sql(name, con, if_exists="replace", index=False)
cur = con.cursor()
for stmt in [
    "CREATE INDEX ix_dep_user ON deposits(user_id)",
    "CREATE INDEX ix_ent_user ON entries(user_id)",
    "CREATE INDEX ix_users_dev ON users(device_id)",
    "CREATE INDEX ix_users_ip ON users(ip_hash)",
    "CREATE INDEX ix_promo_user ON promo_claims(user_id)",
]:
    cur.execute(stmt)
con.commit()

# ground truth (kept OUT of the database on purpose) for checking detection results later
u[["user_id", "fraud_type", "ring_id"]].to_csv("ground_truth_do_not_use_in_sql.csv", index=False)

print("users", len(users_out), "| deposits", len(deposits), "| promo_claims", len(promo_claims),
      "| entries", len(entries), "| withdrawals", len(withdrawals), "| labels", len(fraud_labels))
print(u.fraud_type.value_counts().to_dict())
