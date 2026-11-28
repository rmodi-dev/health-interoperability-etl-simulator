"""Integrity tests for the curated LOINC/UCUM subset CSVs."""

from health_interop.db.reference import load_loinc, load_ucum, loinc_by_code


def test_ucum_entries_are_unique_and_populated() -> None:
    entries = load_ucum()
    assert len(entries) >= 5
    assert len({e.code for e in entries}) == len(entries)


def test_loinc_entries_are_unique_and_populated() -> None:
    entries = load_loinc()
    assert len(entries) == 10
    assert len({e.code for e in entries}) == len(entries)


def test_every_loinc_unit_exists_in_ucum() -> None:
    units = {e.code for e in load_ucum()}
    for entry in load_loinc():
        if entry.ucum_unit is not None:
            assert entry.ucum_unit in units


def test_known_hemoglobin_row() -> None:
    entry = loinc_by_code("718-7")
    assert entry is not None
    assert entry.ucum_unit == "g/dL"
    assert "Hemoglobin" in entry.display


def test_panel_row_has_no_unit() -> None:
    entry = loinc_by_code("58410-2")
    assert entry is not None
    assert entry.ucum_unit is None
