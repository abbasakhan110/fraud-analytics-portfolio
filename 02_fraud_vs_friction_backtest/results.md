# Project 2 results: fraud vs. friction backtest (auto-generated)

Split: TRAIN = signups before 2026-06-01 (31,737 accounts), HOLDOUT = 2026-06-01 and later (27,494 accounts).

Assumptions: chargeback fee $15; 25% of flagged legit users churn; legit-user value $40; review cost $2/flag. (Guesses, not facts.)

## Chosen rule (picked on TRAIN only)

Flag if first deposit >= **$125** OR **2+ earlier accounts** already on the same device OR (disposable email AND deposit within 3h AND 1+ early decline).

## Holdout performance (data the rule never saw)

- Fraud accounts caught: **52.2%** (95% CI 48.2% to 56.0%)
- Fraud $ loss prevented: **64.5%** ($43,675 of $67,695)
- Legit users flagged: **0.38%** (95% CI 0.32% to 0.46%) = 103 people
- Precision: 76.0%
- Net benefit: **$41,785** (bootstrap 95% CI $33,862 to $50,600)

## What each piece of the rule contributes (holdout)

| rule                                       |   fraud_catch_% |   legit_flagged_% |   precision_% |   net_benefit_$ |
|:-------------------------------------------|----------------:|------------------:|--------------:|----------------:|
| amount rule only                           |            14.5 |              0.02 |          94.8 |           26618 |
| shared-device rule only                    |            32.4 |              0.33 |          69.3 |            4329 |
| disposable-email + early decline rule only |            11   |              0.04 |          87.3 |           22842 |
| combined (chosen rule)                     |            52.2 |              0.38 |          76   |           41785 |

## Sensitivity: what if our 'legit user value' assumption is wrong?

|   legit_user_value_$ |   best_amount_t |   best_device_k | disposable_rule   |   holdout_fraud_catch |   holdout_legit_friction |   holdout_net_benefit_$ |
|---------------------:|----------------:|----------------:|:------------------|----------------------:|-------------------------:|------------------------:|
|                   10 |             125 |               2 | True              |                 0.522 |                   0.0038 |                   42558 |
|                   20 |             125 |               2 | True              |                 0.522 |                   0.0038 |                   42300 |
|                   40 |             125 |               2 | True              |                 0.522 |                   0.0038 |                   41785 |
|                   80 |             125 |               2 | True              |                 0.522 |                   0.0038 |                   40755 |
|                  160 |             125 |               2 | True              |                 0.522 |                   0.0038 |                   38695 |

## Top 10 candidate rules on TRAIN

|   amount_t |   device_k | disposable_rule   |   flagged |   fraud_caught |   legit_flagged |   fraud_catch_rate |   precision |   legit_friction_rate |   loss_prevented |   pct_loss_prevented |   friction_cost |   review_cost |   net_benefit |
|-----------:|-----------:|:------------------|----------:|---------------:|----------------:|-------------------:|------------:|----------------------:|-----------------:|---------------------:|----------------:|--------------:|--------------:|
|        125 |          2 | True              |       338 |            303 |              35 |             0.6012 |      0.8964 |                0.0011 |            56065 |               0.7166 |             350 |           676 |         55039 |
|        125 |          3 | True              |       279 |            262 |              17 |             0.5198 |      0.9391 |                0.0005 |            54990 |               0.7029 |             170 |           558 |         54262 |
|        125 |          4 | True              |       240 |            224 |              16 |             0.4444 |      0.9333 |                0.0005 |            53855 |               0.6884 |             160 |           480 |         53215 |
|        125 |          1 | True              |       871 |            351 |             520 |             0.6964 |      0.403  |                0.0166 |            57440 |               0.7342 |            5200 |          1742 |         50498 |
|        150 |          2 | True              |       310 |            278 |              32 |             0.5516 |      0.8968 |                0.001  |            49765 |               0.6361 |             320 |           620 |         48825 |
|        150 |          3 | True              |       251 |            237 |              14 |             0.4702 |      0.9442 |                0.0004 |            48690 |               0.6224 |             140 |           502 |         48048 |
|        150 |          4 | True              |       212 |            199 |              13 |             0.3948 |      0.9387 |                0.0004 |            47555 |               0.6078 |             130 |           424 |         47001 |
|        150 |          1 | True              |       843 |            326 |             517 |             0.6468 |      0.3867 |                0.0166 |            51140 |               0.6537 |            5170 |          1686 |         44284 |
|        125 |          2 | False             |       288 |            257 |              31 |             0.5099 |      0.8924 |                0.001  |            42830 |               0.5475 |             310 |           576 |         41944 |
|        125 |          3 | False             |       229 |            216 |              13 |             0.4286 |      0.9432 |                0.0004 |            41755 |               0.5337 |             130 |           458 |         41167 |
