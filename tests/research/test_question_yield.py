from screen.research.question import half_width_per_dimension, render_yield_summary
from screen.research_trace.replay import TargetYield


def test_half_width_per_dimension():
    # 91 runs, 60 yielded -> p = 0.6593...
    # n=91, p=0.6593, margin ~ 8.1%
    pool = {"agentic": TargetYield(runs=91, yielded=60)}
    margins = half_width_per_dimension(pool)
    assert 0.080 < margins["agentic"] < 0.085


def test_render_yield_summary():
    pool = {
        "agentic": TargetYield(runs=91, yielded=60),
        "location": TargetYield(runs=16, yielded=4),
        "untested": TargetYield(runs=0, yielded=0),
    }
    stalls = {"agentic": 3, "location": 0}
    summary = render_yield_summary("op_1", pool, stalls)

    assert "agentic (65.9%): 0 yielded of 3 attempts on op_1, pool baseline 65.9%" in summary
    assert "location (25.0%): 0 yielded of 0 attempts on op_1, pool baseline 25.0%" in summary
    assert "untested: no pool baseline yet" in summary
