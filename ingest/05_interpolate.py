"""
A4/A5 — daily interpolation. THE KEYSTONE.
Owner: Dev A.

Turns sparse seasonal observations into the daily series the 30-day LSTM needs.

  1. ANCHOR on every real observation - never altered.
  2. RECESSION between observations: exponential decline during dry periods,
     rate fitted per well from its own historical dry-season segments.
  3. RECHARGE pulses driven by precip_mm, scaled by that well's specific_yield.
  4. RECONCILE so the curve lands exactly on the next real observation -
     distribute residual error backwards across the interval.
  5. confidence decays with days-since-nearest-real-observation.
  6. is_observed = TRUE ONLY on genuine measurement dates. Never fudge this.

VALIDATION (A5): hold out every 4th observation, interpolate without it,
measure error at those points. WRITE THE MAE DOWN.

Depends on: weather_daily (handoff H4 from B, due Fri 23:00).
"""
