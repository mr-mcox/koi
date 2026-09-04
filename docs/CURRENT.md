The research-pass bandit is done (research-batch now draws weighted by aggregate
uncertainty, seeded, with a per-turn trace). Its own Not Doing flagged the natural next
friction point: research-batch and bump-research-turns-budget are CLI-only, and now that
the batch actually reasons about which opening to spend on, triggering it and setting its
budget from the web UI (rather than a terminal) is the obvious next surface — no scouting
exists yet for it.
