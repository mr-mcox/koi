-- Drops the per-opening lifetime research-turns cap (0006): the boundary-weighted
-- draw already throttles fully-examined and settled-out openings on its own, and a
-- flat lifetime cap only ever starved still-worth-researching openings once they
-- happened to cross it, with no organic refill (research-targeting.md).
ALTER TABLE openings DROP COLUMN research_turns_budget;
