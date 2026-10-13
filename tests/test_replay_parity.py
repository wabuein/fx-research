from __future__ import annotations

import pytest

from markers import requires_data
from fxresearch.context import ResearchContext
from fxresearch.live.parity import ParityGate
from fxresearch.live.signal import LiveSignalHandler
from fxresearch.structure.pivots import CONFIRM_AT_OPEN

# audjpy showed 23 mismatches before the pivot fix, so it is the sharpest single check
PARITY_INSTRUMENT = "AUDJPY"
RECENT_BARS = 5


@requires_data
def test_live_path_reproduces_the_backtest_bar_for_bar(context: ResearchContext) -> None:
    gate = ParityGate(context, LiveSignalHandler(context))
    result = gate.check_instrument(PARITY_INSTRUMENT, RECENT_BARS)

    assert result.ok
    assert result.checked > 200
    assert result.sig_truth > 0
    assert result.mismatch == 0, result.examples
    assert result.seq_ok


@requires_data
def test_gate_catches_a_pivot_confirmed_one_bar_early() -> None:
    leaky = ResearchContext(confirm_at=CONFIRM_AT_OPEN)
    result = ParityGate(leaky, LiveSignalHandler(leaky)).check_instrument(PARITY_INSTRUMENT, RECENT_BARS)

    assert result.mismatch > 0
