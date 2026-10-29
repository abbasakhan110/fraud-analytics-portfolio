"""
PROJECT 4: Multi-accounting / bonus-abuse ring detection (synthetic data).

Idea: accounts that share a device or IP are linked. Connected groups of linked accounts are
"clusters". Big clusters that all claimed the same signup promo look like bonus-abuse rings.

Steps
  1. SQL self-join builds edges between accounts sharing a device or an IP.
  2. Union-Find (connected components) turns edges into clusters.
  3. Score clusters (size, promo claim rate, disposable email share, minutes between signups).
  4. VALIDATE against the hidden ground truth (only possible because the data is simulated).

Caveat built into the design: IPs are shared by innocent people too (campus / household / mobile
carriers), so IP links alone are weak. Device links are strong. The script shows both.
Usage: python3 detect_rings.py
"""
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

here = Path(__file__).parent
data = here.parent / "data"
con = sqlite3.connect(data / "fraud.db")

# ---------------------------------------------------------------- 1. edges in SQL
EDGES_SQL = """
SELECT a.user_id AS u1, b.user_id AS u2, 'device' AS link
FROM users a JOIN users b ON a.device_id = b.device_id AND a.user_id < b.user_id
UNION ALL
SELECT a.user_id, b.user_id, 'ip'
FROM users a JOIN users b ON a.ip_hash = b.ip_hash AND a.user_id < b.user_id
"""
edges = pd.read_sql_query(EDGES_SQL, con)
print(f"edges: {len(edges):,}  ({edges.link.value_counts().to_dict()})")

users = pd.read_sql_query("""
    SELECT u.user_id, u.signup_ts, u.email_domain, u.device_id, u.ip_hash,
           CASE WHEN pc.user_id IS NULL THEN 0 ELSE 1 END AS claimed_promo,
           COALESCE(pc.bonus_amount, 0) AS bonus_amount,
           CASE WHEN fl.user_id IS NULL THEN 0 ELSE 1 END AS reviewed_fraud
    FROM users u
    LEFT JOIN (SELECT user_id, SUM(bonus_amount) AS bonus_amount FROM promo_claims GROUP BY user_id) pc
           ON pc.user_id = u.user_id
    LEFT JOIN fraud_labels fl ON fl.user_id = u.user_id
""", con)
users["disposable"] = users.email_domain.isin(["tempmail.io", "mailnesia.com"]).astype(int)
users["signup_dt"] = pd.to_datetime(users.signup_ts)
truth = pd.read_csv(data / "ground_truth_do_not_use_in_sql.csv")      # simulation answer key


# ---------------------------------------------------------------- 2. union-find
def build_clusters(edge_df):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for u1, u2 in zip(edge_df.u1.values, edge_df.u2.values):
        r1, r2 = find(u1), find(u2)
        if r1 != r2:
            parent[r2] = r1
    return pd.Series({u: find(u) for u in list(parent)}, name="cluster")


def score_clusters(link_types, min_size=3):
    e = edges[edges.link.isin(link_types)]
    cl = build_clusters(e).reset_index().rename(columns={"index": "user_id"})
    m = cl.merge(users, on="user_id")
    g = m.groupby("cluster")
    out = g.agg(size=("user_id", "count"),
                promo_claim_rate=("claimed_promo", "mean"),
                disposable_share=("disposable", "mean"),
                signup_span_days=("signup_dt", lambda s: (s.max() - s.min()).total_seconds() / 86400),
                bonus_dollars=("bonus_amount", "sum")).reset_index()
    # simple transparent score: big + everyone claimed the promo + signed up close together
    out["risk_score"] = (np.minimum(out["size"], 8) / 8 * 50
                         + out.promo_claim_rate * 30
                         + out.disposable_share * 10
                         + np.where(out.signup_span_days <= 4, 10, 0))
    out["flag_ring"] = (out["size"] >= min_size) & (out.promo_claim_rate >= 0.6) & (out.risk_score >= 60)
    flagged_users = m[m.cluster.isin(out[out.flag_ring].cluster)].user_id
    return out, set(flagged_users)


def evaluate(flagged, label):
    t = truth.set_index("user_id").fraud_type
    is_ring = t.eq("promo_ring")
    pred = pd.Series(t.index.isin(list(flagged)), index=t.index)
    tp = int((pred & is_ring).sum())
    fp = int((pred & ~is_ring).sum())
    fn = int((~pred & is_ring).sum())
    legit_fp = int((pred & t.eq("legit")).sum())
    return {"method": label, "accounts_flagged": int(pred.sum()), "true_ring_accounts_caught": tp,
            "ring_recall_%": round(100 * tp / (tp + fn), 1), "precision_%": round(100 * tp / max(tp + fp, 1), 1),
            "legit_accounts_flagged": legit_fp,
            "legit_flagged_%": round(100 * legit_fp / int(t.eq("legit").sum()), 3)}


results = []
for label, links in [("device links only", ["device"]), ("IP links only", ["ip"]), ("device + IP links", ["device", "ip"])]:
    clusters, flagged = score_clusters(links)
    results.append(evaluate(flagged, label))
    if label == "device links only":
        best_clusters, best_flagged = clusters, flagged
res = pd.DataFrame(results)

# estimated bonus dollars stopped by blocking flagged clusters (device-only method)
bonus_stopped = users[users.user_id.isin(best_flagged)].bonus_amount.sum()

# ---------------------------------------------------------------- 3. report
top = best_clusters[best_clusters.flag_ring].sort_values("risk_score", ascending=False).head(10)
top = top.round({"promo_claim_rate": 2, "disposable_share": 2, "signup_span_days": 2, "risk_score": 1})

md = ["# Project 4 results: multi-account ring detection (auto-generated)\n",
      "Synthetic data. Validation against the simulation's answer key is only possible because the data is simulated; "
      "on real data you would validate with manual review outcomes instead.\n",
      "## Method comparison\n", res.to_markdown(index=False) + "\n",
      f"## Impact\n\nBlocking the clusters flagged by the device-link method would have stopped about **${bonus_stopped:,.0f}** of promo bonus payouts.\n",
      "## Top 10 flagged clusters (device-link method)\n", top.to_markdown(index=False) + "\n",
      "## Why IP-only links are weak\n",
      "Legitimate players share IPs (households, campuses, mobile carriers), so IP links create false clusters. "
      "Device links are much stronger; combining weak and strong signals needs a higher bar (more accounts, tighter signup window).\n"]
(here / "results.md").write_text("\n".join(md))
top.to_csv(here / "top_flagged_clusters.csv", index=False)
print("\n".join(md))
