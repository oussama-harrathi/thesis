from app.utils.chunk_filter import score_generation_chunk


def test_rich_instructional_chunk_scores_above_weak_statement():
    strong = (
        "Theorem. If a graph is connected, then every spanning tree has exactly n - 1 edges. "
        "In contrast, a disconnected graph has no spanning tree. This relationship implies "
        "that connectivity is a necessary condition for the rule to apply."
    )
    weak = "Lecture 4. Page 12. Graph topic overview."

    assert score_generation_chunk(strong) > score_generation_chunk(weak)


def test_exception_and_formula_signals_raise_chunk_score():
    chunk = (
        "If x = y, then f(x) = f(y). However, this equivalence fails unless the stated "
        "conditions hold. The special case is handled by the exception rule."
    )

    assert score_generation_chunk(chunk) > 0.5
