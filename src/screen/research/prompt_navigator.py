"""Live prompt adapter for the Navigate function.

Coerces the generated `baml_client.types.StopAction` into the canonical
`screen.research.actions.StopAction`. Field names match field-for-field;
`tests/research/test_baml_shape.py` pins this at test time.

Target choice is no longer this module's job — the Surveyor (see
`baml_surveyor.py`) picks `state.primary_target` once per pass, before the
dispatcher ever calls `plan()`.
"""

from screen.baml_client.sync_client import BamlSyncClient, b
from screen.extract.prompt import RubricText
from screen.research.actions import Action, FetchAction, SearchAction, StopAction
from screen.research.context import FetchContext
from screen.research.question import render_assertion_history
from screen.research.state import LoopState


def _prior_queries_text(state: LoopState) -> str:
    """Render prior search queries as a short semicolon-joined string.

    Grounds the prompt's "avoid repeating a prior query" instruction in an
    actual value instead of leaving it a dangling template reference.
    """
    if not state.prior_queries:
        return "(none)"
    return "; ".join(state.prior_queries)


def last_context_text(state: LoopState) -> str:
    """Render state.last_context to a short prose paragraph for the navigator.

    Returns an empty string when last_context is None (first cycle).
    """
    ctx = state.last_context
    if ctx is None:
        return ""
    if isinstance(ctx, FetchContext):
        targets = ", ".join(ctx.targets_added) if ctx.targets_added else "(none)"
        snippet_line = f" Snippet: {ctx.snippet!r}" if ctx.snippet else ""
        return (
            f"Last action: fetched {ctx.url}. "
            f"Assertions added for targets: {targets}.{snippet_line}"
        )
    if not ctx.hits:
        return f"Last action: searched {ctx.query!r}. Got 0 hits."
    lines = [f"Last action: searched {ctx.query!r}. Results:"]
    for i, hit in enumerate(ctx.hits, start=1):
        title = hit.get("title") or hit.get("url", "")
        url = hit.get("url", "")
        snippet = hit.get("snippet") or hit.get("raw_content", "")[:300]
        lines.append(f"{i}. {title} — {url}\n   {snippet}")
    return "\n".join(lines)


class PromptNavigator:
    """Calls Navigate via the generated BAML sync client.

    Trusts `state.primary_target`/`state.research_question` as already set —
    the dispatcher gets them from the Surveyor once per pass, before the loop
    starts, and this navigator never recomputes either. `rubric` is the
    process-wide loaded rubric, narrowed per call to just `primary_target`'s
    text: the dimension is fixed for the whole pass, so the other dimensions'
    anchors can only distract from it.
    """

    def __init__(self, rubric: RubricText, client: BamlSyncClient = b) -> None:
        self._rubric = rubric
        self._client = client

    def plan(self, state: LoopState) -> list[Action]:
        if state.primary_target is None:
            raise RuntimeError(
                "PromptNavigator.plan() called before the Surveyor set primary_target. "
                "The dispatcher must survey before the first decide_plan call."
            )
        generated = self._client.Navigate(
            company_name=state.company_name,
            opening_title=state.opening_title,
            rubric_text=self._rubric.for_dimension(state.primary_target),
            primary_target=state.primary_target,
            research_question=state.research_question or "",
            last_context_text=last_context_text(state),
            prior_queries=_prior_queries_text(state),
            assertion_history=render_assertion_history(state.assertions, [state.primary_target]),
            link_backlog=state.link_backlog,
        )
        return [_coerce(g) for g in generated]


def _coerce(generated: object) -> Action:
    """Translate a generated BAML action to the canonical domain type.

    Raises RuntimeError on an unrecognized tag — same discipline as the
    dispatcher so the error surfaces before dispatch, not inside it.
    """
    tag = getattr(generated, "tag", None)
    reason = getattr(generated, "reason", "")
    url = getattr(generated, "url", "")

    if tag == "stop":
        return StopAction(reason=str(reason))

    if tag == "fetch":
        return FetchAction(url=str(url))

    if tag == "search":
        query = getattr(generated, "query", "")
        return SearchAction(query=str(query))

    raise RuntimeError(
        f"PromptNavigator received unrecognized action tag '{tag}' from Navigate. "
        "Update navigator.baml and add a coercion branch here."
    )
