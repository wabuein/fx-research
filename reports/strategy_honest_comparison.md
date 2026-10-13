# Honest head-to-head: V1 / V2 / V3, broker candles, look-ahead-free, net 1x cost
strategy                           n    PF   win%     avgR   totR  green%  OOS_PF  OOS_tot
V1 Structure+ATR (2of3)        42450  0.74   35.1  -0.1908  -8100    5.1%    0.75    -3048
V1 Structure+ATR (enhanced)        0   (no trades)
V2 Corner-AOI (2of3)            3818  0.77   36.2  -0.1576   -602   26.7%    0.76     -300
V3 4H-Corner (as written)        179  0.85   35.8  -0.1009    -18   43.0%    1.11        5

REFERENCE (distilled edge after the pivot fix, KEEP12 pairs, 1x cost, see reports/edge_gauntlet.md):
  d4 + fresh corner + 5R single:  PF 0.96  avg -0.0307R  total -42R  OOS_PF 0.87

Cost sensitivity (avg net R/trade):
strategy                           0.5x       1x       2x
V1 Structure+ATR (2of3)         -0.1130  -0.1908  -0.3465
V2 Corner-AOI (2of3)            -0.1001  -0.1576  -0.2726
V3 4H-Corner (as written)       -0.0485  -0.1009  -0.2055
