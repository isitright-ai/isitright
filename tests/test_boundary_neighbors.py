"""The neighbors of a boundary value are written the way the value is."""

from __future__ import annotations

import pytest

from isitright.core.families._util import neighbors


@pytest.mark.parametrize(
    ("kind", "value", "below", "above"),
    [
        ("datetime", "2024-05-14T15:00:00", "2024-05-14T14:59:59", "2024-05-14T15:00:01"),
        ("datetime", "2024-05-14T15:00:00Z", "2024-05-14T14:59:59Z", "2024-05-14T15:00:01Z"),
        ("datetime", "2024-05-14 15:00:00", "2024-05-14 14:59:59", "2024-05-14 15:00:01"),
        (
            "datetime",
            "2024-05-14T15:00:00+02:00",
            "2024-05-14T14:59:59+02:00",
            "2024-05-14T15:00:01+02:00",
        ),
        ("date", "2024-05-14", "2024-05-13", "2024-05-15"),
    ],
)
def test_neighbors_keep_the_style_of_the_value(
    kind: str, value: str, below: str, above: str
) -> None:
    assert neighbors(kind, value) == [value, below, above]
