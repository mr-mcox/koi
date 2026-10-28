"""Pairwise comparison workflow: which pair to ask about next, Jev's provisional
ruling on it, and the prescreen engine that runs ahead of the operator.

The fit that turns rulings into dimension posteriors is not here — it lives in
`screen.score.pairwise`, because pool ranking consumes it and this package reads
the ranked pool.
"""
