"""Comparison policies for data answers: tolerance and its basis, named answers, frames, text."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("pandas")

from isitright.packs.data.comparison import (
    AnswerPolicy,
    CannotJudge,
    DataComparator,
    FramePolicy,
    decimals_in,
    named_answers,
    normalize_answer,
    undefined_answer,
)


def frame(
    columns: list[str], data: list[list[object]], dtypes: list[str], index: list[int]
) -> dict:
    return {"__frame__": {"columns": columns, "dtypes": dtypes, "index": index, "data": data}}


def test_the_decimals_a_question_asks_for_set_the_tolerance_and_its_basis() -> None:
    assert decimals_in("Round to two decimal places.") == 2
    assert decimals_in("rounded to 4 decimal places and also to 2 decimal places") == 2
    assert decimals_in("no rounding mentioned") is None
    policy = AnswerPolicy.for_question("Round your answer to 2 decimal places.")
    assert policy.abs_tol == pytest.approx(0.01) and "2 decimal places" in policy.basis
    default = AnswerPolicy.for_question("How many?")
    assert default.abs_tol == 1e-9 and "floating-point noise" in default.basis


def test_one_unit_in_the_last_place_survives_float_noise_at_large_magnitudes() -> None:
    cmp = DataComparator(AnswerPolicy.for_question("rounded to 2 decimal places"))
    # a rounding that differs by one unit at a tie, on numbers of a few million
    assert cmp.compare({"m": 2243963.3}, "@m[2243963.31]").matches
    assert cmp.compare({"m": 2268418.13}, "@m[2268418.14]").matches
    assert cmp.compare({"m": 2243963.31}, "@m[2243963.3]").matches
    assert not cmp.compare({"m": 2243963.3}, "@m[2243963.32]").matches  # two units apart
    assert not cmp.compare({"m": 1.0}, "@m[1.02]").matches


def test_the_policy_goes_into_the_report_with_its_basis() -> None:
    described = DataComparator(AnswerPolicy.for_question("2 decimal places")).describe()
    assert described["numbers"]["basis"].startswith("question asks for 2")
    assert described["text"] == "normalized"


def test_named_answers_in_the_benchmark_format_are_parsed() -> None:
    assert named_answers("@a[1.50] @Mean Fare[2]") == {"a": 1.5, "meanfare": 2.0}
    assert named_answers("no pairs here") is None
    assert normalize_answer("@yes[ Yes ]") == {"yes": "Yes"}
    assert normalize_answer({"type": "number", "value": 3}) == 3.0


def test_numbers_match_within_the_tolerance_and_text_after_normalization() -> None:
    cmp = DataComparator(AnswerPolicy.for_question("2 decimal places"))
    assert cmp.compare({"m": 1.234}, "@m[1.24]").matches
    miss = cmp.compare({"m": 1.0}, "@m[1.5]")
    assert not miss.matches and "answer[m]" in (miss.difference or "")
    assert cmp.compare({"s": "Yes"}, "@s[yes]").matches
    assert not cmp.compare({"a": 1.0}, "@b[1]").matches
    assert not cmp.compare({"a": 1.0}, "narrative text").matches


def test_a_list_answer_matches_a_comma_separated_string() -> None:
    cmp = DataComparator()
    assert cmp.compare({"c": ["Kuwait", "Saudi Arabia"]}, "@c[Kuwait, Saudi Arabia]").matches
    assert cmp.compare({"c": []}, "@c[]").matches
    assert not cmp.compare({"c": ["Kuwait"]}, "@c[Kuwait, Oman]").matches


def test_an_answer_that_is_not_data_cannot_be_judged() -> None:
    result = DataComparator().compare({"a": 1}, {"a": {"__other__": "Foo: <obj>"}})
    assert result.inconclusive and not result.matches
    with pytest.raises(CannotJudge):
        normalize_answer({"__other__": "x"})


def test_an_undefined_reference_answer_is_not_compared() -> None:
    assert undefined_answer({"m": {"__float__": "nan"}})
    assert undefined_answer("@m[nan]")
    assert not undefined_answer({"m": 1.0})
    assert DataComparator().compare({"m": float("nan")}, "@m[nan]").matches


def test_frames_compare_by_column_dtype_kind_and_values() -> None:
    left = frame(["a", "b"], [[1, 2.0], [3, 4.0]], ["int64", "float64"], [0, 1])
    same = frame(["a", "b"], [[1, 2.0], [3, 4.0]], ["int64", "float64"], [5, 6])
    assert DataComparator().compare(left, same).matches  # the index is ignored by default
    strict = DataComparator(AnswerPolicy(frame=FramePolicy(index="strict")))
    assert not strict.compare(left, same).matches
    other_dtype = frame(["a", "b"], [[1, 2.0], [3, 4.0]], ["Int64", "float32"], [0, 1])
    assert DataComparator().compare(left, other_dtype).matches  # same kind
    text_dtype = frame(["a", "b"], [["1", 2.0], ["3", 4.0]], ["object", "float64"], [0, 1])
    assert "dtype" in (DataComparator().compare(left, text_dtype).difference or "")
    exact = DataComparator(AnswerPolicy(frame=FramePolicy(dtype="strict")))
    assert not exact.compare(left, other_dtype).matches
    swapped = frame(["b", "a"], [[2.0, 1], [4.0, 3]], ["float64", "int64"], [0, 1])
    assert not DataComparator().compare(left, swapped).matches
    free = DataComparator(AnswerPolicy(frame=FramePolicy(column_order="ignore")))
    assert free.compare(left, swapped).matches
    reordered = frame(["a", "b"], [[3, 4.0], [1, 2.0]], ["int64", "float64"], [0, 1])
    assert not DataComparator().compare(left, reordered).matches
    rows_free = DataComparator(AnswerPolicy(frame=FramePolicy(row_order="ignore")))
    assert rows_free.compare(left, reordered).matches
    short = frame(["a", "b"], [[1, 2.0]], ["int64", "float64"], [0])
    assert "row count" in (DataComparator().compare(left, short).difference or "")
    assert "table" in (DataComparator().compare(left, 3.0).difference or "")


def test_a_list_of_names_has_no_order_but_the_same_names() -> None:
    cmp = DataComparator()
    assert cmp.compare({"c": ["Kuwait", "Saudi Arabia"]}, "@c[Saudi Arabia, Kuwait]").matches
    assert not cmp.compare({"c": ["Kuwait", "Oman"]}, "@c[Saudi Arabia, Kuwait]").matches
    assert not cmp.compare({"c": [1.0, 2.0]}, "@c[2, 1]").matches  # numbers keep their order


def test_quote_characters_around_a_name_or_list_item_are_not_part_of_it() -> None:
    cmp = DataComparator()
    expected = {"c": ["Kuwait", "Saudi Arabia"]}
    assert cmp.compare(expected, "@c['Kuwait', 'Saudi Arabia']").matches
    assert cmp.compare(expected, '@c["Saudi Arabia", "Kuwait"]').matches
    assert cmp.compare(expected, "@c[['Kuwait', 'Saudi Arabia']]").matches  # the brackets too
    assert cmp.compare({"country": "Congo"}, "@country['Congo']").matches
    assert not cmp.compare(expected, "@c['Kuwait', 'Oman']").matches


BLOCKS = (
    "@continent_name[africa]\n@r[0.43]\n@sig[non-significant]\n"
    "@continent_name[asia]\n@r[0.38]\n@sig[non-significant]\n"
    "@continent_name[europe]\n@r[0.78]\n@sig[significant]\n"
)


def groups(*rows: tuple[str, float, str]) -> list[dict[str, object]]:
    return [{"continent_name": c, "r": r, "sig": s} for c, r, s in rows]


def test_a_repeated_block_of_answers_is_a_list_of_groups_compared_without_order() -> None:
    parsed = named_answers(BLOCKS)
    assert parsed is not None and len(parsed["__records__"]) == 3
    assert parsed["__records__"][1] == {
        "continentname": "asia",
        "r": 0.38,
        "sig": "non-significant",
    }
    cmp = DataComparator(AnswerPolicy.for_question("rounded to two decimal places"))
    ordered = groups(
        ("africa", 0.43, "non-significant"),
        ("asia", 0.38, "non-significant"),
        ("europe", 0.78, "significant"),
    )
    assert cmp.compare(ordered, BLOCKS).matches
    assert cmp.compare(list(reversed(ordered)), BLOCKS).matches  # the order of groups is free
    wrong_value = groups(
        ("africa", 0.43, "non-significant"),
        ("asia", 0.99, "non-significant"),
        ("europe", 0.78, "significant"),
    )
    miss = cmp.compare(wrong_value, BLOCKS)
    assert not miss.matches and "asia" in (miss.difference or "")
    missing_group = groups(("africa", 0.43, "non-significant"), ("asia", 0.38, "non-significant"))
    assert "3 groups" in (cmp.compare(missing_group, BLOCKS).difference or "") or (
        "2 groups" in (cmp.compare(missing_group, BLOCKS).difference or "")
    )
    renamed = groups(
        ("africa", 0.43, "non-significant"),
        ("asia", 0.38, "non-significant"),
        ("oceania", 0.78, "significant"),
    )
    assert "no group" in (cmp.compare(renamed, BLOCKS).difference or "")
    assert not cmp.compare(ordered, "@r[0.43]").matches  # groups against a single answer
    assert not cmp.compare({"r": 0.43}, BLOCKS).matches  # a single answer against groups


# --- 0.9: exactly 2 ulps, and decimals per named answer ------------------------------------------

PEARSON = (
    "Calculate the Pearson correlation between x and y. Format: @r_value[r_value] "
    '@p_value[p_value] where "r_value" is a number rounded to two decimal places, and '
    '"p_value" is a number rounded to four decimal places.'
)


def test_the_ulp_margin_is_exactly_the_number_of_ulps_stated() -> None:
    from isitright.core.compare import NumericComparator

    two = NumericComparator(0.0, 0.0, "exact", ulps=2)
    one_step = math.nextafter(1.0, 2.0)
    two_steps = math.nextafter(one_step, 2.0)
    three_steps = math.nextafter(two_steps, 2.0)
    assert two.compare(1.0, two_steps).matches
    assert not two.compare(1.0, three_steps).matches
    assert not NumericComparator(0.0, 0.0, "exact").compare(1.0, one_step).matches


def test_a_tie_one_unit_apart_matches_with_two_ulps_and_no_relative_term() -> None:
    policy = AnswerPolicy.for_question("Round to two decimal places.")
    assert (policy.abs_tol, policy.rel_tol, policy.ulps) == (0.01, 0.0, 2)
    numbers = policy.describe()["numbers"]
    assert numbers["ulps"] == 2 and numbers["rel_tol"] == 0.0
    assert DataComparator(policy).compare(2243963.30, 2243963.31).matches
    assert not DataComparator(policy).compare(2243963.30, 2243963.32).matches


def test_each_named_answer_gets_the_decimals_its_own_clause_states() -> None:
    policy = AnswerPolicy.for_question(PEARSON)
    assert policy.abs_tol == 0.01 and policy.per_answer == {"pvalue": 4}
    described = policy.describe()["numbers_per_answer"]["pvalue"]
    assert described["abs_tol"] == 0.0001 and "4 decimal places for pvalue" in described["basis"]
    comparator = DataComparator(policy)
    expected = "@r_value[0.53] @p_value[0.0012]"
    assert comparator.compare(expected, "@r_value[0.539] @p_value[0.0012]").matches  # r: 0.01
    outcome = comparator.compare(expected, "@r_value[0.53] @p_value[0.0019]")
    assert not outcome.matches and "pvalue" in (outcome.difference or "")
    # 0.6 to 0.8 used the fewest decimals for every answer and accepted this
    assert (
        DataComparator(AnswerPolicy(abs_tol=0.01, rel_tol=0.0, ulps=2))
        .compare(expected, "@r_value[0.53] @p_value[0.0019]")
        .matches
    )


RESPECTIVELY = (
    "Format: @r_value[r_value] @p_value[p_value] where r_value and p_value are rounded to "
    "two decimal places and four decimal places respectively."
)


def test_respectively_gives_each_answer_its_precision_in_order() -> None:
    policy = AnswerPolicy.for_question(RESPECTIVELY)
    assert policy.per_answer == {"pvalue": 4} and policy.undetermined == {}
    assert policy.abs_tol == 0.01
    comparator = DataComparator(policy)
    expected = "@r_value[0.53] @p_value[0.0012]"
    assert comparator.compare(expected, "@r_value[0.539] @p_value[0.0012]").matches
    outcome = comparator.compare(expected, "@r_value[0.53] @p_value[0.0019]")
    assert not outcome.matches and "pvalue" in (outcome.difference or "")


def test_respectively_follows_the_order_the_answers_are_listed_in() -> None:
    text = (
        "Format: @r_value[r_value] @p_value[p_value] where p_value and r_value are rounded to "
        "two decimal places and four decimal places respectively."
    )
    policy = AnswerPolicy.for_question(text)
    assert policy.per_answer == {"rvalue": 4} and policy.abs_tol == 0.01  # p_value: 2, r_value: 4


def test_a_precision_the_text_does_not_settle_is_reported_and_taken_at_its_finest() -> None:
    # three answers, two precisions, "respectively": the pairing is not given
    unmatched = (
        "Format: @a[a] @b[b] @c[c] where a, b and c are rounded to two decimal places and four "
        "decimal places respectively."
    )
    policy = AnswerPolicy.for_question(unmatched)
    assert policy.undetermined == {"a": [2, 4], "b": [2, 4], "c": [2, 4]}
    assert policy.per_answer == {"a": 4, "b": 4, "c": 4}
    split = (
        "Format: @r_value[r_value] @p_value[p_value] where r_value is rounded to two decimal "
        "places and p_value to four decimal places or to six decimal places."
    )
    policy = AnswerPolicy.for_question(split)
    assert policy.undetermined == {"pvalue": [4, 6]} and policy.per_answer == {"pvalue": 6}
    note = policy.describe()["precision_undetermined"]["pvalue"]
    assert note["named"] == [4, 6] and note["used"] == 6 and "finest" in note["note"]
    assert "without saying which applies" in policy.numeric("pvalue").describe()["basis"]
    comparator = DataComparator(policy)
    expected = "@r_value[0.53] @p_value[0.0012]"
    assert not comparator.compare(expected, "@r_value[0.53] @p_value[0.00121]").matches
    assert comparator.compare(expected, "@r_value[0.53] @p_value[0.0012000004]").matches
    # a policy with nothing undetermined says nothing about it
    assert "precision_undetermined" not in AnswerPolicy.for_question(PEARSON).describe()
