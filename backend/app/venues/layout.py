"""Seat-layout generation.

Deliberately pure: no session, no ORM. The geometry is the part worth testing
directly, and the service layer only has to persist what comes out.
"""

from dataclasses import dataclass

from app.core.errors import validation_error
from app.schemas.venue import LayoutCategory


@dataclass(frozen=True)
class GeneratedSeat:
    row_label: str
    row_index: int
    seat_number: int
    category_name: str
    x: int
    y: int


def row_label_for(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA. Spreadsheet-style, so >26 rows still work."""
    if index < 0:
        raise ValueError("row index must be non-negative")
    label = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


def row_index_for(label: str) -> int:
    """Inverse of row_label_for."""
    label = label.strip().upper()
    if not label or not label.isalpha():
        raise ValueError(f"invalid row label {label!r}")
    value = 0
    for char in label:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def seat_x(seat_number: int, aisle_after_columns: list[int]) -> int:
    """Stored x for a 1-based seat number.

    x = seat_number + (number of aisles already passed), so a seat sitting
    just after an aisle lands one unit further right than its neighbour count
    would suggest and the client renders the gap without knowing the rule.

    With aisle_after_columns [3, 15]: seat 3 -> 3, seat 4 -> 5 (jumped),
    seat 15 -> 16, seat 16 -> 18 (jumped again).
    """
    return seat_number + sum(1 for column in aisle_after_columns if column < seat_number)


def resolve_category_rows(
    rows: int, categories: list[LayoutCategory]
) -> dict[int, str]:
    """Map each row index to its category name, or explain why it cannot."""
    assignment: dict[int, str] = {}
    for category in categories:
        try:
            start = row_index_for(category.row_from)
            end = row_index_for(category.row_to)
        except ValueError as exc:
            raise validation_error(str(exc)) from exc

        if start > end:
            raise validation_error(
                f"category {category.name!r}: row_from {category.row_from} is "
                f"after row_to {category.row_to}"
            )
        if end >= rows:
            raise validation_error(
                f"category {category.name!r}: row_to {category.row_to} is beyond "
                f"the last row ({row_label_for(rows - 1)})"
            )
        for index in range(start, end + 1):
            if index in assignment:
                raise validation_error(
                    f"row {row_label_for(index)} is claimed by both "
                    f"{assignment[index]!r} and {category.name!r}"
                )
            assignment[index] = category.name

    missing = [row_label_for(i) for i in range(rows) if i not in assignment]
    if missing:
        raise validation_error(
            "every row must belong to a category; unassigned: "
            + ", ".join(missing)
        )
    return assignment


def generate_seats(
    rows: int,
    seats_per_row: int,
    aisle_after_columns: list[int],
    categories: list[LayoutCategory],
) -> list[GeneratedSeat]:
    """Produce every seat for a screen, in render order (y, then x)."""
    assignment = resolve_category_rows(rows, categories)
    aisles = sorted(aisle_after_columns)

    seats: list[GeneratedSeat] = []
    for row_index in range(rows):
        label = row_label_for(row_index)
        for seat_number in range(1, seats_per_row + 1):
            seats.append(
                GeneratedSeat(
                    row_label=label,
                    row_index=row_index,
                    seat_number=seat_number,
                    category_name=assignment[row_index],
                    x=seat_x(seat_number, aisles),
                    y=row_index,
                )
            )
    return seats
