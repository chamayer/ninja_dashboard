"""Compatibility result type for intelligence material-change producers."""

from __future__ import annotations


class MaterialCount(int):
    """An integer row count with an explicit material-change outcome.

    Existing diagnostics and callers can continue treating this value as an
    ``int``.  Governed Jobs admission reads ``material_changed`` rather than
    guessing from a positive count, because a refresh count is not necessarily
    a changed-output count.
    """

    material_changed: bool

    def __new__(cls, value: int, *, material_changed: bool):
        instance = int.__new__(cls, value)
        instance.material_changed = material_changed
        return instance
