from __future__ import annotations

from markers import requires_data
from fxresearch.context import ResearchContext
from fxresearch.engine.metrics import in_sample, measure, out_of_sample
from fxresearch.strategies.edge import LOCKED_CONFIG, EdgeFrames


@requires_data
def test_canonical_5r_config_matches_the_corrected_findings(context: ResearchContext,
                                                            keep12_frames: list[EdgeFrames]) -> None:
    trades = context.edge_strategy(LOCKED_CONFIG).run_all(keep12_frames)

    full, is_m, oos_m = measure(trades), measure(in_sample(trades)), measure(out_of_sample(trades))
    assert (full.n, full.avg, full.pf) == (1372, -0.0307, 0.96)
    assert (is_m.n, is_m.avg, is_m.pf) == (837, 0.0216, 1.03)
    assert (oos_m.n, oos_m.avg, oos_m.pf) == (535, -0.1127, 0.87)


@requires_data
def test_baseline_2r_config_matches_the_corrected_findings(context: ResearchContext,
                                                           keep12_frames: list[EdgeFrames]) -> None:
    trades = context.edge_strategy(LOCKED_CONFIG).with_config(target_rr=2.0).run_all(keep12_frames)

    full = measure(trades)
    assert (full.n, full.avg, full.pf) == (1486, -0.1138, 0.84)
