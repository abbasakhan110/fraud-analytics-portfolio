-- ============================================================================
-- PROJECT 1: SQL fraud analysis (synthetic fantasy-sports-style platform)
-- Skills shown: joins, CTEs, aggregations, window functions (ROW_NUMBER, LAG,
-- running SUM, COUNT OVER), CASE bucketing.
-- Convention: a user is "fraud" if they appear in fraud_labels (confirmed by review).
-- Each block starts with "-- name:" so run_queries.py can run and label it.
-- ============================================================================

-- name: q01_overview_funnel_by_signup_month
-- Question: how many people sign up, how many deposit, and how many are confirmed fraud each month?
WITH first_dep AS (
    SELECT user_id, MIN(deposit_ts) AS first_deposit_ts
    FROM deposits
    WHERE status IN ('success', 'chargeback')
    GROUP BY user_id
)
SELECT
    SUBSTR(u.signup_ts, 1, 7)                                   AS signup_month,
    COUNT(*)                                                    AS signups,
    COUNT(fd.user_id)                                           AS depositors,
    ROUND(100.0 * COUNT(fd.user_id) / COUNT(*), 1)              AS deposit_conv_pct,
    COUNT(fl.user_id)                                           AS confirmed_fraud,
    ROUND(100.0 * COUNT(fl.user_id) / COUNT(*), 2)              AS fraud_rate_pct
FROM users u
LEFT JOIN first_dep fd    ON fd.user_id = u.user_id
LEFT JOIN fraud_labels fl ON fl.user_id = u.user_id
GROUP BY signup_month
ORDER BY signup_month;

-- name: q02_fraud_rate_by_email_domain
-- Question: which email domains are over-represented in fraud? (a classic onboarding signal)
SELECT
    u.email_domain,
    COUNT(*)                                          AS accounts,
    COUNT(fl.user_id)                                 AS fraud_accounts,
    ROUND(100.0 * COUNT(fl.user_id) / COUNT(*), 2)    AS fraud_rate_pct
FROM users u
LEFT JOIN fraud_labels fl ON fl.user_id = u.user_id
GROUP BY u.email_domain
ORDER BY fraud_rate_pct DESC;

-- name: q03_first_deposit_speed_vs_fraud
-- Question: do fraudsters deposit faster than real players?
-- Window function: ROW_NUMBER picks each user's FIRST successful deposit.
WITH ranked AS (
    SELECT
        d.user_id, d.amount, d.deposit_ts,
        ROW_NUMBER() OVER (PARTITION BY d.user_id ORDER BY d.deposit_ts) AS rn
    FROM deposits d
    WHERE d.status IN ('success', 'chargeback')
),
first_dep AS (
    SELECT r.user_id, r.amount,
           (julianday(r.deposit_ts) - julianday(u.signup_ts)) * 24 * 60 AS minutes_to_first_dep
    FROM ranked r
    JOIN users u ON u.user_id = r.user_id
    WHERE r.rn = 1
)
SELECT
    CASE WHEN minutes_to_first_dep <= 60    THEN '1) within 1 hour'
         WHEN minutes_to_first_dep <= 360   THEN '2) 1-6 hours'
         WHEN minutes_to_first_dep <= 1440  THEN '3) 6-24 hours'
         ELSE                                    '4) > 24 hours' END       AS time_to_first_deposit,
    COUNT(*)                                                               AS depositors,
    COUNT(fl.user_id)                                                      AS fraud_accounts,
    ROUND(100.0 * COUNT(fl.user_id) / COUNT(*), 2)                         AS fraud_rate_pct,
    ROUND(AVG(f.amount), 2)                                                AS avg_first_deposit
FROM first_dep f
LEFT JOIN fraud_labels fl ON fl.user_id = f.user_id
GROUP BY 1
ORDER BY 1;

-- name: q04_first_deposit_amount_vs_fraud
-- Question: does a big first deposit predict fraud?
WITH ranked AS (
    SELECT user_id, amount,
           ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY deposit_ts) AS rn
    FROM deposits WHERE status IN ('success', 'chargeback')
)
SELECT
    CASE WHEN r.amount < 20  THEN '1) under $20'
         WHEN r.amount < 50  THEN '2) $20-49'
         WHEN r.amount < 100 THEN '3) $50-99'
         WHEN r.amount < 200 THEN '4) $100-199'
         ELSE                     '5) $200+' END       AS first_deposit_size,
    COUNT(*)                                           AS depositors,
    COUNT(fl.user_id)                                  AS fraud_accounts,
    ROUND(100.0 * COUNT(fl.user_id) / COUNT(*), 2)     AS fraud_rate_pct
FROM ranked r
LEFT JOIN fraud_labels fl ON fl.user_id = r.user_id
WHERE r.rn = 1
GROUP BY 1
ORDER BY 1;

-- name: q05_payment_decline_and_chargeback_by_method
-- Question: which payment methods have the worst decline and chargeback rates?
SELECT
    method,
    COUNT(*)                                                                     AS attempts,
    ROUND(100.0 * SUM(status = 'declined')   / COUNT(*), 2)                      AS decline_rate_pct,
    ROUND(100.0 * SUM(status = 'chargeback') / NULLIF(SUM(status <> 'declined'), 0), 2) AS chargeback_rate_pct,
    ROUND(SUM(CASE WHEN status = 'chargeback' THEN amount ELSE 0 END), 0)        AS chargeback_dollars
FROM deposits
GROUP BY method
ORDER BY chargeback_dollars DESC;

-- name: q06_accounts_with_many_declines_in_first_day
-- Question: card-testing pattern -> 3+ declined deposits within 24h of signup.
-- Window function: COUNT(*) OVER (PARTITION BY user_id) counts declines per user.
WITH early_declines AS (
    SELECT d.user_id,
           COUNT(*) OVER (PARTITION BY d.user_id) AS declines_day1
    FROM deposits d
    JOIN users u ON u.user_id = d.user_id
    WHERE d.status = 'declined'
      AND julianday(d.deposit_ts) - julianday(u.signup_ts) <= 1
),
per_user AS (SELECT DISTINCT user_id, declines_day1 FROM early_declines)
SELECT
    CASE WHEN declines_day1 >= 3 THEN '3+ declines' ELSE '1-2 declines' END AS bucket,
    COUNT(*)                                          AS accounts,
    COUNT(fl.user_id)                                 AS fraud_accounts,
    ROUND(100.0 * COUNT(fl.user_id) / COUNT(*), 1)    AS fraud_rate_pct
FROM per_user p
LEFT JOIN fraud_labels fl ON fl.user_id = p.user_id
GROUP BY 1;

-- name: q07_promo_cost_by_fraud_status
-- Question: how many bonus dollars go to confirmed fraud accounts?
SELECT
    CASE WHEN fl.user_id IS NULL THEN 'not confirmed fraud' ELSE fl.fraud_type END AS segment,
    COUNT(*)                          AS claims,
    ROUND(SUM(pc.bonus_amount), 0)    AS bonus_dollars,
    ROUND(100.0 * SUM(pc.bonus_amount) / SUM(SUM(pc.bonus_amount)) OVER (), 1) AS pct_of_all_bonus_dollars
FROM promo_claims pc
LEFT JOIN fraud_labels fl ON fl.user_id = pc.user_id
GROUP BY segment
ORDER BY bonus_dollars DESC;

-- name: q08_weekly_chargeback_loss_with_wow_change
-- Question: how does weekly chargeback loss trend? (LAG for week-over-week, running SUM for cumulative)
WITH weekly AS (
    SELECT STRFTIME('%Y-W%W', chargeback_ts) AS week,
           SUM(amount)                       AS chargeback_dollars
    FROM deposits
    WHERE status = 'chargeback'
    GROUP BY week
)
SELECT
    week,
    ROUND(chargeback_dollars, 0)                                                   AS chargeback_dollars,
    ROUND(100.0 * (chargeback_dollars - LAG(chargeback_dollars) OVER (ORDER BY week))
          / NULLIF(LAG(chargeback_dollars) OVER (ORDER BY week), 0), 1)           AS wow_change_pct,
    ROUND(SUM(chargeback_dollars) OVER (ORDER BY week), 0)                         AS cumulative_dollars
FROM weekly
ORDER BY week
LIMIT 40;

-- name: q09_devices_shared_across_accounts
-- Question: how common is device sharing, and how fraud-heavy are shared devices?
WITH dev AS (
    SELECT device_id, COUNT(*) AS accounts_on_device
    FROM users GROUP BY device_id
)
SELECT
    CASE WHEN d.accounts_on_device = 1 THEN '1 account'
         WHEN d.accounts_on_device = 2 THEN '2 accounts'
         WHEN d.accounts_on_device BETWEEN 3 AND 4 THEN '3-4 accounts'
         ELSE '5+ accounts' END                           AS accounts_on_device,
    COUNT(*)                                              AS users,
    COUNT(fl.user_id)                                     AS fraud_accounts,
    ROUND(100.0 * COUNT(fl.user_id) / COUNT(*), 1)        AS fraud_rate_pct
FROM users u
JOIN dev d ON d.device_id = u.device_id
LEFT JOIN fraud_labels fl ON fl.user_id = u.user_id
GROUP BY 1
ORDER BY 1;
