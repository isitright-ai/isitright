from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


def load_constraints() -> dict[str, Any]:
    path = Path("tests/fixtures/proposals/constraints.yaml")
    schema: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return schema


def test_constraints_are_valid_json_schema_draft_2020_12() -> None:
    Draft202012Validator.check_schema(load_constraints())


def test_constraints_accept_a_valid_normalized_snapshot() -> None:
    snapshot = {
        "hubs": [{"hub_id": 1, "code": "HBR", "zone": "coastal"}],
        "shipments": [
            {
                "shipment_id": 1,
                "hub_id": 1,
                "tracking_code": None,
                "package_count": 3,
                "declared_weight": 2.5,
                "status": "queued",
                "shipped_at": None,
                "delivered_at": None,
            }
        ],
        "couriers": [{"courier_id": 1, "hub_id": 1, "name": "Mara", "active": 1}],
    }
    Draft202012Validator(load_constraints()).validate(snapshot)


@pytest.mark.parametrize(
    ("field", "value"),
    [("package_count", 0), ("status", "lost")],
)
def test_constraints_reject_invalid_shipment_domain_values(field: str, value: object) -> None:
    shipment = {
        "shipment_id": 1,
        "hub_id": 1,
        "tracking_code": "PKG-X1",
        "package_count": 3,
        "declared_weight": 2.5,
        "status": "queued",
    }
    shipment[field] = value
    snapshot = {
        "hubs": [{"hub_id": 1, "code": "HBR", "zone": "coastal"}],
        "shipments": [shipment],
        "couriers": [],
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(load_constraints()).validate(snapshot)
