# Results at the gate: 12 FX pairs, 2015-2026, net of 1.5x modeled cost

IS = 2015-2021, OOS = 2022-2026. avg is net R per trade. Gate = net positive in both IS and OOS.

| TF | Config | Account | n | Full avg / PF | IS avg / PF | OOS avg / PF | Gate |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 4H | d4, fresh corner, 1xATR stop, 5R (the old headline config) | Standard | 1372 | -0.0544 / 0.94 | -0.0016 / 1.00 | -0.1372 / 0.84 | fail |
| 4H | d4, fresh corner, 1xATR stop, 5R (the old headline config) | Raw | 1372 | -0.0875 / 0.90 | -0.0345 / 0.96 | -0.1703 / 0.81 | fail |
| 4H | d4, fresh corner, 2xATR stop, 3R (best cell found) | Standard | 1127 | +0.0054 / 1.01 | +0.0504 / 1.08 | -0.0641 / 0.91 | fail (OOS) |
| 4H | d4, fresh corner, 2xATR stop, 3R (best cell found) | Raw | 1127 | -0.0111 / 0.98 | +0.0338 / 1.05 | -0.0804 / 0.88 | fail (OOS) |
| 1H | 4H+1H bias, 4H/D corners, 2xATR stop, 5R | Standard | 6998 | -0.0959 / 0.86 | -0.0820 / 0.88 | -0.1172 / 0.83 | fail |
| 1H | 4H+1H bias, 4H/D corners, 2xATR stop, 5R | Raw | 6998 | -0.1318 / 0.82 | -0.1184 / 0.84 | -0.1522 / 0.79 | fail |
