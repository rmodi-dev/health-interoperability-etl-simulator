"""Persistence layer: declarative schema, sessions and repositories.

Schema layout (medallion-style, with explicit lineage):
    raw   immutable landing records, one row per inbound message
    stg   parsed and normalised per-observation rows
    core  curated clinical entities that passed data-quality gating
    dq    data-quality findings and quarantine reasons
    fhir  projected FHIR R4B resources
"""
