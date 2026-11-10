"""Species identifiers and categories (ADR-0033).

A species is addressed by a readable slug of its scientific name, the same on
every station, so detections of many stations merge without a lookup table.
"""

from __future__ import annotations

import re
from typing import Literal

#: Open enum. ``human`` and ``environment`` are sound classes an analyzer
#: reports that are not species, such as speech or engines.
SpeciesCategory = Literal[
    "bird", "bat", "mammal", "amphibian", "insect", "human", "environment", "other"
]

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def species_id(scientific_name: str) -> str:
    """Return the species slug: lowercase, runs of non-alphanumerics become ``-``.

    >>> species_id("Turdus merula")
    'turdus-merula'
    """
    return _NON_ALNUM.sub("-", scientific_name.lower()).strip("-")
