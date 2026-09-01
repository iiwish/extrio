import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


class ContractBundle:
    def __init__(self, contract_path: Path):
        self.contract_path = contract_path
        self.openapi = yaml.safe_load((contract_path / "openapi.yaml").read_text())
        self.gather_schema = json.loads((contract_path / "gather-spec.schema.json").read_text())
        self.rule_plan_schema = json.loads((contract_path / "rule-plan.schema.json").read_text())
        self.rule_attestation_schema = json.loads((contract_path / "rule-attestation.schema.json").read_text())
        self._gather_template = json.loads((contract_path / "gather-spec.example.json").read_text())
        self._gather_validator = Draft202012Validator(self.gather_schema, format_checker=FormatChecker())
        self._rule_plan_validator = Draft202012Validator(self.rule_plan_schema, format_checker=FormatChecker())
        self._rule_attestation_validator = Draft202012Validator(
            self.rule_attestation_schema,
            format_checker=FormatChecker(),
        )

    def validate_gather_spec(self, spec: dict[str, Any]) -> None:
        self._gather_validator.validate(spec)

    def validate_rule_attestation(self, attestation: dict[str, Any]) -> None:
        self._rule_attestation_validator.validate(attestation)

    def validate_rule_plan(self, plan: dict[str, Any]) -> None:
        self._rule_plan_validator.validate(plan)

    def gather_template(self) -> dict[str, Any]:
        return copy.deepcopy(self._gather_template)


def sha256_digest(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"
