"""Curated reference vocabularies loaded from versioned CSVs.

File-based on purpose: these vocabularies are inputs to validation rules, not
clinical data. Keeping them out of the database means no seeded "reference"
rows can ever be mistaken for pipeline output.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "reference"
LOINC_CSV = DATA_DIR / "loinc_subset.csv"
UCUM_CSV = DATA_DIR / "ucum_units.csv"


class ReferenceDataError(ValueError):
    """The curated reference files are internally inconsistent."""


@dataclass(frozen=True, slots=True)
class LoincEntry:
    code: str
    display: str
    ucum_unit: str | None


@dataclass(frozen=True, slots=True)
class UcumEntry:
    code: str
    display: str


@lru_cache(maxsize=1)
def load_ucum() -> tuple[UcumEntry, ...]:
    with UCUM_CSV.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    entries = tuple(
        UcumEntry(code=r["ucum_code"].strip(), display=r["display"].strip()) for r in rows
    )
    codes = [e.code for e in entries]
    if len(codes) != len(set(codes)):
        raise ReferenceDataError(f"duplicate UCUM codes in {UCUM_CSV.name}")
    if any(not e.code or not e.display for e in entries):
        raise ReferenceDataError(f"empty UCUM field in {UCUM_CSV.name}")
    return entries


@lru_cache(maxsize=1)
def load_loinc() -> tuple[LoincEntry, ...]:
    units = {e.code for e in load_ucum()}
    with LOINC_CSV.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    entries: list[LoincEntry] = []
    for row in rows:
        unit = row["ucum_unit"].strip() or None
        if unit is not None and unit not in units:
            raise ReferenceDataError(
                f"LOINC row {row['loinc_code']} references unknown UCUM unit {unit!r}"
            )
        entries.append(
            LoincEntry(
                code=row["loinc_code"].strip(), display=row["display"].strip(), ucum_unit=unit
            )
        )
    codes = [e.code for e in entries]
    if len(codes) != len(set(codes)):
        raise ReferenceDataError(f"duplicate LOINC codes in {LOINC_CSV.name}")
    if any(not e.code or not e.display for e in entries):
        raise ReferenceDataError(f"empty LOINC field in {LOINC_CSV.name}")
    return tuple(entries)


def loinc_by_code(code: str) -> LoincEntry | None:
    for entry in load_loinc():
        if entry.code == code:
            return entry
    return None
