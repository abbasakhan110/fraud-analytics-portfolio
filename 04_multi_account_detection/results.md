# Project 4 results: multi-account ring detection (auto-generated)

Synthetic data. Validation against the simulation's answer key is only possible because the data is simulated; on real data you would validate with manual review outcomes instead.

## Method comparison

| method            |   accounts_flagged |   true_ring_accounts_caught |   ring_recall_% |   precision_% |   legit_accounts_flagged |   legit_flagged_% |
|:------------------|-------------------:|----------------------------:|----------------:|--------------:|-------------------------:|------------------:|
| device links only |                593 |                         593 |            75.9 |         100   |                        0 |             0     |
| IP links only     |                585 |                         494 |            63.3 |          84.4 |                       77 |             0.133 |
| device + IP links |               1144 |                         676 |            86.6 |          59.1 |                      454 |             0.783 |

## Impact

Blocking the clusters flagged by the device-link method would have stopped about **$16,740** of promo bonus payouts.

## Top 10 flagged clusters (device-link method)

|   cluster |   size |   promo_claim_rate |   disposable_share |   signup_span_days |   bonus_dollars |   risk_score | flag_ring   |
|----------:|-------:|-------------------:|-------------------:|-------------------:|----------------:|-------------:|:------------|
|     26875 |      8 |                  1 |               0.75 |               2.26 |             235 |         97.5 | True        |
|     25007 |      8 |                  1 |               0.62 |               2.49 |             210 |         96.2 | True        |
|     53593 |      8 |                  1 |               0.5  |               1.93 |             235 |         95   | True        |
|     56960 |      8 |                  1 |               0.38 |               2.11 |             235 |         93.8 | True        |
|     54385 |      8 |                  1 |               0.25 |               1.96 |             195 |         92.5 | True        |
|     46884 |      7 |                  1 |               0.86 |               2.4  |             215 |         92.3 | True        |
|     28795 |      7 |                  1 |               0.71 |               2.34 |             185 |         90.9 | True        |
|     47887 |      7 |                  1 |               0.71 |               2.1  |             205 |         90.9 | True        |
|      8706 |      7 |                  1 |               0.57 |               2.37 |             155 |         89.5 | True        |
|      4740 |      7 |                  1 |               0.57 |               2.33 |             160 |         89.5 | True        |

## Why IP-only links are weak

Legitimate players share IPs (households, campuses, mobile carriers), so IP links create false clusters. Device links are much stronger; combining weak and strong signals needs a higher bar (more accounts, tighter signup window).
