from isitright.core.minimize import ddmin as reduce_rows


def test_reduction_removes_chunks_but_preserves_required_rows() -> None:
    reduction = reduce_rows([0, 1, 2, 3], max_attempts=50, accepts=lambda rows: 1 in rows)
    assert reduction.kept == [1]
    assert reduction.complete
    assert reduction.attempts > 0


def test_reduction_reports_budget_exhaustion_without_claiming_minimality() -> None:
    reduction = reduce_rows([0, 1, 2], max_attempts=1, accepts=lambda rows: False)
    assert reduction.kept == [0, 1, 2]
    assert reduction.attempts == 1
    assert not reduction.complete
    empty = reduce_rows([], max_attempts=0, accepts=lambda rows: False)
    assert empty.complete and empty.attempts == 0
