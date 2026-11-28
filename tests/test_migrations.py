"""Migration tests: the migrated database must equal the model metadata.

`alembic check` runs autogenerate in dry-run mode and raises CommandError when
it detects any drift - this is the guard that keeps migrations and models honest.
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_alembic_head_is_applied(db_session: Session) -> None:
    version = db_session.execute(
        text("select version_num from public.alembic_version")
    ).scalar_one()
    assert version == "0001"


@pytest.mark.integration
def test_no_drift_between_models_and_migrated_db(alembic_config: Config) -> None:
    command.check(alembic_config)  # raises CommandError if models and DB disagree


@pytest.mark.integration
def test_all_five_schemas_exist(db_session: Session) -> None:
    names = set(
        db_session.execute(text("select schema_name from information_schema.schemata")).scalars()
    )
    assert {"raw", "stg", "core", "dq", "fhir"} <= names
