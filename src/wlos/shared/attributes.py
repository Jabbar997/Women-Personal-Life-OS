from __future__ import annotations

from datetime import date, datetime

type ScalarValue = str | int | float | bool | datetime | date | None
type AttributeValue = ScalarValue | list[ScalarValue] | dict[str, ScalarValue]
type Attributes = dict[str, AttributeValue]
"""Open attribute bag for graph primitives.

Deliberately not ``Any``: entity types with a known shape are validated against
a typed schema (see ``wlos.personal_life_graph.schemas``), and this bag carries
only the long tail.
"""
