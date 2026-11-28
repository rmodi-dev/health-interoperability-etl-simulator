"""Foundation smoke tests: prove the dependency set works on Python 3.12.

Every clinical value in this file is SYNTHETIC.

Two typing decisions, both deliberate:
* FHIR resources are built from typed model classes (Coding / CodeableConcept /
  Quantity) rather than raw dicts: fhir.resources >= 8.2.0 adds TYPE_CHECKING
  type aliases, so dict literals fail static typing even though pydantic
  accepts them at runtime.
* Quantity.value is a FHIR decimal -> decimal.Decimal. Lab values are carried
  as Decimal, never float, to avoid binary rounding of clinical results.
"""

from decimal import Decimal

import sqlalchemy
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.quantity import Quantity
from hl7apy.consts import VALIDATION_LEVEL
from hl7apy.parser import parse_message

import health_interop

SYNTHETIC_ORU_R01 = (
    "MSH|^~\\&|SYNTH_LIS|LAB|SYNTH_EMR|CLINIC|20261126080000||ORU^R01|SYN0001|P|2.5.1\r"
    "PID|1||SYN-MRN-0001^^^SYNTH^MR||SYNTHETIC^Test^A||19800101|M\r"
    "OBR|1|ORD-0001|FIL-0001|718-7^Hemoglobin^LN|||20261126073000\r"
    "OBX|1|NM|718-7^Hemoglobin^LN||13.5|g/dL|12.0-16.0|N|||F\r"
)


def test_package_version_is_exposed() -> None:
    assert health_interop.__version__ == "0.1.0"


def test_sqlalchemy_is_on_the_2_0_series() -> None:
    assert sqlalchemy.__version__.startswith("2.0.")


def test_fhir_r4b_models_construct_and_serialize() -> None:
    patient = Patient(id="synth-patient-1", gender="unknown")
    observation = Observation(
        status="final",
        code=CodeableConcept(
            coding=[
                Coding(
                    system="http://loinc.org",
                    code="718-7",
                    display="Hemoglobin",
                )
            ]
        ),
        valueQuantity=Quantity(
            value=Decimal("13.5"),
            unit="g/dL",
            system="http://unitsofmeasure.org",
            code="g/dL",
        ),
    )
    assert patient.get_resource_type() == "Patient"
    assert observation.get_resource_type() == "Observation"
    assert observation.valueQuantity is not None
    assert observation.valueQuantity.value == Decimal("13.5")

    # mode="json" yields JSON-compatible primitives (FHIR wire shape).
    payload = observation.model_dump(mode="json", exclude_none=True)
    assert payload["resourceType"] == "Observation"
    assert payload["code"]["coding"][0]["code"] == "718-7"


def test_hl7apy_parses_synthetic_oru_r01() -> None:
    message = parse_message(SYNTHETIC_ORU_R01, validation_level=VALIDATION_LEVEL.TOLERANT)
    msh_9 = message.msh.msh_9
    # hl7apy's dynamic child lookup is typed ElementProxy | None (its
    # _default_child_lookup can fall through). MSH-9 is mandatory in a parsed
    # message, so assert the invariant: narrows the type AND guards runtime.
    assert msh_9 is not None
    assert msh_9.to_er7() == "ORU^R01"
