# Metric dictionary (synthetic fraud & payments platform)

One place that says what each number means, so two people never report two different "fraud rates."
Grain = the level the metric is calculated at. Source = tables in `fraud.db`.

| Metric | Definition | Formula | Grain | Source | Watch out for |
|---|---|---|---|---|---|
| Signups | New accounts created | COUNT(users) | week of `signup_ts` | users | Includes fraudulent accounts |
| Deposit conversion % | Share of signups that make at least one successful deposit | depositors / signups | signup week | users, deposits | Recent cohorts are still converting (people deposit days later) |
| Depositor | User with at least one deposit whose status is `success` or `chargeback` | MIN(deposit_ts) per user where status <> declined | user | deposits | A declined attempt alone does not count |
| Confirmed fraud account | User present in `fraud_labels` (confirmed by manual review) | COUNT(fraud_labels.user_id) | signup week | fraud_labels | **Lagging**: review takes 5 to 20 days, so recent weeks are understated |
| Confirmed fraud account rate % | Confirmed fraud accounts as a share of signups | confirmed fraud / signups | signup week | users, fraud_labels | Same lag as above; compare only mature weeks |
| Decline rate % | Share of deposit attempts the processor declined | declined attempts / all attempts | deposit week | deposits | Card testing inflates it; one fraudster can create many declines |
| Chargeback $ | Deposit dollars later reversed by the card issuer | SUM(amount) where status = chargeback | deposit week | deposits | Arrives 7 to 30 days after the deposit |
| Chargeback rate % | Chargeback dollars as a share of successful deposit dollars | chargeback $ / successful deposit $ | deposit week | deposits | **Only report mature cohorts** (deposit week at least 30 days old) |
| Bonus $ paid | Promo bonus dollars granted | SUM(bonus_amount) | claim week | promo_claims | Not all bonus $ is a loss; most goes to real players |
| Bonus $ to fraud % | Share of bonus dollars granted to confirmed fraud accounts | bonus to fraud / all bonus | period | promo_claims, fraud_labels | Understated if fraud is undetected |
| Prior accounts on device | Accounts that signed up earlier on the same device | window COUNT over device ordered by signup | user | users | Must be **point in time** (only earlier accounts) or a backtest leaks the future |
| Legit friction rate % | Share of legitimate users a rule flags | flagged legit / all legit | rule, period | features + labels | "Legit" really means "not confirmed fraud" |
| Fraud catch rate % | Share of fraud accounts a rule flags | flagged fraud / all fraud | rule, period | features + labels | Bounded by label quality |

## Data-quality checks run on every refresh

1. **Volume check**: deposits per hour vs the median of the same hour over the previous 14 days. Flag 3+ consecutive hours below 35% of expected.
2. **Duplicate check**: rows with the same user, timestamp and amount. Flag any day above 1% duplicates.
3. **Maturity check**: hide or label any metric that depends on delayed events (chargebacks, fraud labels).
