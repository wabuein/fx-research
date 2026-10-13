from __future__ import annotations

from markers import requires_data
from fxresearch.context import ResearchContext
from fxresearch.engine.metrics import measure, out_of_sample
from fxresearch.strategies.edge import LOCKED_CONFIG, EdgeFrames

# the original bug: daily and weekly pivots stamped at the rightmost candle's open instead of its close,
# so every corner became usable one bar before it existed
MIN_SUSPICIOUS_GAIN_R = 0.05


@requires_data
def test_confirming_pivots_one_bar_early_looks_suspiciously_better(
        context: ResearchContext, keep12_frames: list[EdgeFrames], leaky_keep12_frames: list[EdgeFrames]) -> None:
    strategy = context.edge_strategy(LOCKED_CONFIG)
    causal = strategy.run_all(keep12_frames)
    leaky = strategy.run_all(leaky_keep12_frames)

    causal_m, leaky_m = measure(causal), measure(leaky)
    assert leaky_m.avg - causal_m.avg > MIN_SUSPICIOUS_GAIN_R
    assert leaky_m.pf > causal_m.pf
    assert measure(out_of_sample(leaky)).pf > measure(out_of_sample(causal)).pf
    assert causal_m.avg < 0 < leaky_m.avg
