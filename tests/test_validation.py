from collections.abc import Iterable, Mapping, Sequence

from isitright.packs.sql.models import CanonicalValue, CanonicalValueKind
from isitright.packs.sql.validation import (
    CandidateStateValidator,
    CandidateStateView,
    ValidationFinding,
    ValidatorResult,
    ValidatorStatus,
)


class ExampleState:
    @property
    def engine(self) -> str:
        return "sqlite"

    def table_names(self) -> Sequence[str]:
        return ["shipments"]

    def rows(self, table: str) -> Iterable[Mapping[str, CanonicalValue]]:
        assert table == "shipments"
        return [
            {
                "package_count": CanonicalValue(
                    kind=CanonicalValueKind.INTEGER, value=0, engine_type="INTEGER"
                )
            }
        ]


class ExampleValidator:
    @property
    def name(self) -> str:
        return "positive-package-count"

    def __call__(self, state: CandidateStateView) -> ValidatorResult:
        assert state.engine == "sqlite"
        return ValidatorResult(
            validator_name=self.name,
            status=ValidatorStatus.INVALID,
            checked_rules=["package-count-positive"],
            findings=[
                ValidationFinding(
                    rule_id="package-count-positive",
                    message="package_count must be positive",
                    location="shipments[0].package_count",
                )
            ],
        )


def test_trusted_validator_protocol_is_structured_and_engine_neutral() -> None:
    state = ExampleState()
    validator = ExampleValidator()
    assert isinstance(state, CandidateStateView)
    assert isinstance(validator, CandidateStateValidator)
    result = validator(state)
    assert result.status is ValidatorStatus.INVALID
    assert result.findings[0].location == "shipments[0].package_count"


def test_validator_status_distinguishes_indeterminate_from_not_run() -> None:
    assert [status.value for status in ValidatorStatus] == [
        "VALID",
        "INVALID",
        "INDETERMINATE",
    ]
