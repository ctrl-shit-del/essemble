"""Seat-layout geometry.

The point of storing x/y at all is that the client should not have to infer
where the aisles are. If x ever equals seat_number for a seat sitting past an
aisle, the coordinates carry no information the client did not already have.
"""

import pytest

from app.core.errors import AppError
from app.schemas.venue import LayoutCategory
from app.venues.layout import (
    generate_seats,
    row_index_for,
    row_label_for,
    seat_x,
)

AISLES = [3, 15]

CATEGORIES = [
    LayoutCategory(name="VIP", rank=1, row_from="A", row_to="C"),
    LayoutCategory(name="Premium", rank=2, row_from="D", row_to="G"),
    LayoutCategory(name="Standard", rank=3, row_from="H", row_to="L"),
]

#: seat_number -> expected x for aisle_after_columns [3, 15].
#: 1..3 sit before the first aisle; 4..15 are shifted by one; 16..18 by two.
EXPECTED_X = {
    1: 1, 2: 2, 3: 3,
    4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10, 10: 11,
    11: 12, 12: 13, 13: 14, 14: 15, 15: 16,
    16: 18, 17: 19, 18: 20,
}


def test_seat_x_matches_expected_table() -> None:
    for seat_number, expected in EXPECTED_X.items():
        assert seat_x(seat_number, AISLES) == expected


def test_seat_four_jumps_the_first_aisle() -> None:
    # The specific case worth naming: seat 4 is the first seat past an aisle.
    assert seat_x(3, AISLES) == 3
    assert seat_x(4, AISLES) == 5
    assert seat_x(4, AISLES) - seat_x(3, AISLES) == 2


def test_seat_sixteen_jumps_the_second_aisle() -> None:
    assert seat_x(15, AISLES) == 16
    assert seat_x(16, AISLES) == 18


def test_aisles_actually_affect_x() -> None:
    """Guards against the parameter being accepted and then ignored."""
    shifted = [n for n in range(1, 19) if seat_x(n, AISLES) != n]
    assert shifted == list(range(4, 19))


def test_no_aisles_leaves_x_equal_to_seat_number() -> None:
    for seat_number in range(1, 19):
        assert seat_x(seat_number, []) == seat_number


def test_full_12x18_screen() -> None:
    seats = generate_seats(12, 18, AISLES, CATEGORIES)

    assert len(seats) == 216

    by_position = {(s.row_label, s.seat_number): s for s in seats}
    for (row, number), seat in by_position.items():
        assert seat.x == EXPECTED_X[number], f"{row}{number}"

    # y is the row index: A -> 0 ... L -> 11.
    assert {s.row_label: s.y for s in seats}["A"] == 0
    assert {s.row_label: s.y for s in seats}["L"] == 11

    # Every row is 18 wide and spans x = 1..20 with two gaps.
    row_a = sorted(s.x for s in seats if s.row_label == "A")
    assert len(row_a) == 18
    assert row_a[0] == 1 and row_a[-1] == 20
    assert set(range(1, 21)) - set(row_a) == {4, 17}


def test_categories_map_to_the_right_rows() -> None:
    seats = generate_seats(12, 18, AISLES, CATEGORIES)
    by_row = {s.row_label: s.category_name for s in seats}
    assert [by_row[r] for r in "ABC"] == ["VIP"] * 3
    assert [by_row[r] for r in "DEFG"] == ["Premium"] * 4
    assert [by_row[r] for r in "HIJKL"] == ["Standard"] * 5


def test_row_labels_round_trip_past_z() -> None:
    assert row_label_for(0) == "A"
    assert row_label_for(25) == "Z"
    assert row_label_for(26) == "AA"
    for index in (0, 3, 25, 26, 51, 100):
        assert row_index_for(row_label_for(index)) == index


def test_uncovered_row_is_rejected() -> None:
    partial = [LayoutCategory(name="VIP", rank=1, row_from="A", row_to="C")]
    with pytest.raises(AppError) as exc:
        generate_seats(12, 18, AISLES, partial)
    assert "unassigned" in exc.value.message


def test_overlapping_categories_are_rejected() -> None:
    overlapping = [
        LayoutCategory(name="VIP", rank=1, row_from="A", row_to="F"),
        LayoutCategory(name="Premium", rank=2, row_from="D", row_to="L"),
    ]
    with pytest.raises(AppError) as exc:
        generate_seats(12, 18, AISLES, overlapping)
    assert "claimed by both" in exc.value.message
