# Bearing: Jev Assertion Classification and Confidence
parent: (root)
status: orienting

## Context
We are migrating assertion evaluation from a single-shot BAML prompt to a two-step pipeline: BAML extracts the quote, Jev classifies the fit. This exposes Jev's confidence score, which we will use to scale the Monte Carlo scorer's variance, and a separate relevance judgment, which lets us drop junk claims before they ever hit the database. Clear claims get narrow variance; muddy claims get wide variance; irrelevant fragments are discarded.

## Commitments

### 1. Two-Stage Extraction
We will split the intake pipeline. BAML acts as a wide net, identifying targets and extracting verbatim quotes + citations. Jev will then evaluate the quote against the `rubric.yaml` text to determine the `Fit`.

### 2. Irrelevance Filtering via Jev
LLM extractors (BAML) are prone to pulling generic or unhelpful quotes (e.g., extracting "United States" for `location`). Instead of trying to prompt-engineer BAML to drop them, we will use Jev to filter them out. Jev's classification will include an explicit `Irrelevant` / `Insufficient Information` option (or a pre-qualifying `bool` question).
- If a quote is junk, Jev flags it irrelevant, and it is dropped before hitting the database.
- *Nuance:* As defined in the rubric, the *absence* of information in a broad chunk (e.g., a responsibilities section lacking AI/ML) is valid `Poor` evidence. Jev's criteria will distinguish between "this is a broad section proving a negative" (Relevant -> Poor) vs "this is an isolated, useless fragment" (Irrelevant -> Drop).
- A real craft-direction example like Instacart's backend/system-integration requirements is relevant but `Poor`; it's the right kind of evidence for the question, but the wrong kind of work.

### 3. Confidence as Variance
We will capture the classification confidence score and pipe it into the Monte Carlo scorer. Currently, `src/screen/api/scoring.py` derives prior variance purely from assertion count. We will replace or modify this so that lower confidence directly widens the variance.

### 4. Backfill Active Openings
We will backfill classification for non-archived opportunities so the live pool reflects the new relevance filter and confidence-aware scoring without waiting for fresh intake. Archived history is left alone unless explicitly re-opened.

### 5. Jev API Integration
We will integrate the actual TypeSafe Python SDK to call Jev in the pipeline for classification.

## Not Doing
- We are not changing the Monte Carlo ranking logic itself (sorting by `P(value > bar)`). We are only changing the shape of the priors fed into it.
- We are not auto-rejecting or dropping *low-confidence relevant* claims; they remain in the pool, their wide variance simply means they contribute less certainty to the rank. Only *irrelevant* claims are dropped.

## Recalibrate When
- If the TypeSafe API latency for Jev adds unacceptable overhead to the intake queue.
- If mapping Jev's confidence (0.0 - 1.0) to the scorer's variance equations distorts the rankings compared to the current count-based baseline.