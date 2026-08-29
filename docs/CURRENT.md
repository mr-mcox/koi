Two open threads from the assertion-ratings and dimension-digest work landed side by side:

The queue page (`_queue_items` in `src/screen/web/routes.py`) scores every opening via `score_opening(assertions, config)` with no rulings — only the per-opening rating page applies recorded `AssertionRuling`s. The queue's standing/band can silently disagree with what the rating page shows for the same opening. Orient on whether the queue should apply rulings too (and, if so, whether that's a query cost worth paying on every queue render).

Research passes silently truncate at the search-budget cap (dispatcher.py:87 forces a stop without ever asking the planner, no terminal StopAction logged) and the rating view surfaces nothing about it (no searches-used/budget, no incomplete-pass indicator) — see docs/features/review-ux/scouting-2026-08-29.md F25-F31. Orient on whether this is a lightweight fix now or belongs to the not-yet-built ResearchQueue/VOI mechanism (open-questions.md #4, #10).
