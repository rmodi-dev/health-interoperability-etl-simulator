"""Foundation smoke tests: prove the dependency set works on Python 3.12.

Every clinical value in this file is SYNTHETIC.
"""

import sqlalchemy
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.patient import Patient
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
        code={
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "718-7",
                    "display": "Hemoglobin",
                }
            ]
        },
        valueQuantity={
            "value": 13.5,
            "unit": "g/dL",
            "system": "http://unitsofmeasure.org",
            "code": "g/dL",
        },
    )
    assert patient.get_resource_type() == "Patient"
    assert observation.get_resource_type() == "Observation"
    payload = observation.model_dump(exclude_none=True)
    assert payload["resourceType"] == "Observation"
    assert payload["valueQuantity"]["value"] == 13.5


def test_hl7apy_parses_synthetic_oru_r01() -> None:
    message = parse_message(SYNTHETIC_ORU_R01, validation_level=VALIDATION_LEVEL.TOLERANT)
    assert message.msh.msh_9.to_er7() == "ORU^R01"