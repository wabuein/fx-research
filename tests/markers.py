from __future__ import annotations

import pytest

from fxresearch.data.dukascopy import DukascopyHandler
from fxresearch.data.instruments import KEEP12

HAS_H1_DATA = all(DukascopyHandler().has(instrument, "h1") for instrument in KEEP12)
requires_data = pytest.mark.skipif(not HAS_H1_DATA, reason="dukascopy h1 data missing, see data/README.md")
