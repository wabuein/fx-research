# Edge strategy gauntlet: d4 bias + fresh corner AOI, target 5.0R, stop 1.0xATR, AOI tol 0.75xATR
Entry: +1 4H bar open after signal. One position/instrument at a time. Net of modeled cost.
Years 2015-2026 | 1372 trades (~114/yr) | IS<2022=837 OOS>=2022=535

## Headline (1x modeled cost)
  full       n=1372  win=19.8%  net=  -42.2R  avg=-0.0307R  PF= 0.96  maxDD= 108.3R
  in-sample  n= 837  win=21.4%  net=   18.1R  avg=+0.0216R  PF= 1.03  maxDD=  80.2R
  out-sample n= 535  win=17.2%  net=  -60.3R  avg=-0.1127R  PF= 0.87  maxDD=  67.9R

## Cost sensitivity (net), full / IS / OOS
  0x(gross) full avg=+0.0167  net=  22.9R | IS avg=+0.0680 net=  56.9R | OOS avg=-0.0636 net= -34.0R
  0.5x      full avg=-0.0070  net=  -9.6R | IS avg=+0.0448 net=  37.5R | OOS avg=-0.0881 net= -47.1R
  1.0x      full avg=-0.0307  net= -42.2R | IS avg=+0.0216 net=  18.1R | OOS avg=-0.1127 net= -60.3R
  2.0x      full avg=-0.0781  net=-107.2R | IS avg=-0.0247 net= -20.7R | OOS avg=-0.1617 net= -86.5R

## Per year (net, 1x)
  2015  n=106  win=24.5%  net=  13.3R  avg=+0.1259
  2016  n=115  win=23.5%  net=  27.8R  avg=+0.2417
  2017  n=124  win=18.5%  net= -15.5R  avg=-0.1249  <-
  2018  n=115  win=19.1%  net= -11.0R  avg=-0.0961  <-
  2019  n=110  win=23.6%  net=  19.0R  avg=+0.1725
  2020  n=112  win=24.1%  net=  -0.3R  avg=-0.0027  <-
  2021  n=155  win=18.1%  net= -15.2R  avg=-0.0979  <-
  2022  n=103  win=19.4%  net=   3.7R  avg=+0.0357
  2023  n=131  win=15.3%  net= -25.7R  avg=-0.1958  <-
  2024  n=130  win=16.9%  net=  -8.7R  avg=-0.0669  <-
  2025  n=113  win=15.0%  net= -38.1R  avg=-0.3371  <-
  2026  n= 58  win=22.4%  net=   8.5R  avg=+0.1466

## Per instrument (net, 1x), IS vs OOS
  USDCAD   IS n= 56 net=  15.5R avg=+0.2762 | OOS n= 52 net=   6.7R avg=+0.1294
  USDJPY   IS n= 63 net=  27.3R avg=+0.4339 | OOS n= 32 net=  -8.8R avg=-0.2738
  EURGBP   IS n= 67 net=  15.8R avg=+0.2352 | OOS n= 53 net=  -4.0R avg=-0.0762
  EURUSD   IS n= 75 net=  -1.8R avg=-0.0239 | OOS n= 51 net=   9.5R avg=+0.1863
  EURJPY   IS n= 72 net=  -1.4R avg=-0.0200 | OOS n= 44 net=   6.6R avg=+0.1495
  GBPUSD   IS n= 80 net=  -4.4R avg=-0.0549 | OOS n= 39 net=   1.6R avg=+0.0420
  AUDUSD   IS n= 69 net=  12.9R avg=+0.1876 | OOS n= 56 net= -18.3R avg=-0.3265
  GBPCHF   IS n= 71 net= -15.8R avg=-0.2229 | OOS n= 48 net=   7.5R avg=+0.1564
  NZDUSD   IS n= 69 net=  14.5R avg=+0.2108 | OOS n= 47 net= -25.1R avg=-0.5343
  NZDJPY   IS n= 70 net=  -7.2R avg=-0.1022 | OOS n= 43 net=  -6.8R avg=-0.1572
  AUDJPY   IS n= 63 net=  -9.5R avg=-0.1506 | OOS n= 30 net= -10.5R avg=-0.3501
  GBPJPY   IS n= 82 net= -27.9R avg=-0.3398 | OOS n= 40 net= -18.8R avg=-0.4692

## IS-locked whitelist (instruments IS-net-positive, >=5 IS trades), tested OOS
  whitelist (5): AUDUSD, EURGBP, NZDUSD, USDCAD, USDJPY
  all OOS        n= 535  win=17.2%  net=  -60.3R  avg=-0.1127R  PF= 0.87  maxDD=  67.9R
  whitelist OOS  n= 240  win=15.8%  net=  -49.5R  avg=-0.2061R  PF= 0.77  maxDD=  57.1R

## Parameter sweeps (full-sample net avg R/trade; OOS avg in parens): plateau check
### target RR
   1.5R   n=1591  avg=-0.0992  (OOS -0.1352)
  1.75R   n=1527  avg=-0.1066  (OOS -0.1373)
   2.0R   n=1486  avg=-0.1138  (OOS -0.1685)
  2.25R   n=1455  avg=-0.1260  (OOS -0.2236)
   2.5R   n=1439  avg=-0.1031  (OOS -0.1904)
### stop xATR
  0.75    n=1541  avg=-0.1253  (OOS -0.1527)
   1.0    n=1372  avg=-0.0307  (OOS -0.1127)
  1.25    n=1256  avg=-0.0133  (OOS -0.1149)
   1.5    n=1183  avg=+0.0011  (OOS -0.0964)
### AOI tolerance xATR
   0.5    n=1069  avg=-0.0227  (OOS -0.1014)
  0.75    n=1372  avg=-0.0307  (OOS -0.1127)
   1.0    n=1651  avg=-0.0809  (OOS -0.1358)
   1.5    n=2372  avg=-0.0902  (OOS -0.1254)
### bias mode
  d4      n=1372  avg=-0.0307  (OOS -0.1127)
  bias2   n=4207  avg=-0.0580  (OOS -0.1037)
  bias3   n= 665  avg=-0.0322  (OOS -0.2106)

