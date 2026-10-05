---
title: Loss Ratio — metric definition (Finance & Claims Analytics)
---

# Loss Ratio (LR)

**Definition.** Loss ratio measures how much of the premium is paid back out in losses. It is
reported monthly by line of business.

**Calculation.** Incurred losses divided by written premium, for the same line of business and
accounting month, expressed as a percentage.

- Incurred losses = paid losses (CLAIM_PMT_SV, PMT_TYPE_CD = 'L') plus the change in case
  reserves over the month.
- Premium = written premium for the month from POLICY_EXPOSURE_SV.

**Exclusions.** Catastrophe-coded claims (CAT_IND = 'Y') are excluded from the standard loss
ratio and reported separately.

Owner: Claims Analytics. Questions to #claims-analytics.
