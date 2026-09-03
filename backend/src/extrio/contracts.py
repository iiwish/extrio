import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


class SemanticContractError(ValueError):
    """Raised when a contract passes JSON Schema but breaks offline semantic rules."""


# Constructs that leave the RE2-compatible subset documented for regex_extract.
# RE2 has no backtracking engine: lookahead, lookbehind and backreferences are
# unsupported. Compliance at run time is enforced by the RE2 engine itself;
# this offline guard gives reviewers a deterministic, early rejection.
_NON_RE2_CONSTRUCTS = (
    r"\(\?=",          # lookahead (?=...)
    r"\(\?!",          # negative lookahead (?!...)
    r"\(\?<",          # lookbehind (?<=..., (?<!...) and PCRE named groups (?<name>...)
    r"\(\?P=",         # named backreference (?P=name)
    r"\(\?'",          # PCRE group without angle brackets (?'
    r"\(\?&",          # subroutine call (?&name)
    r"\(\?#",          # comment group (?#...)
    r"\(\?[CRUJ]",     # PCRE verbs and verb modifiers
    r"\(\?\d",         # conditional group (?(1)then|else)
    r"(?<!\\)\\[1-9]", # backreference \1 .. \9 (not an escaped literal)
)
_NON_RE2 = re.compile("|".join(_NON_RE2_CONSTRUCTS))


def re2_pattern_error(pattern: str) -> str | None:
    """Return a stable rejection reason when *pattern* leaves the RE2 subset, else None."""
    if not isinstance(pattern, str) or not pattern:
        return "pattern must be a non-empty string"
    if len(pattern.encode("utf-8")) > 512:
        return "pattern exceeds the 512-byte limit"
    found = _NON_RE2.search(pattern)
    if found:
        return (
            f"pattern uses non-RE2 construct {found.group(0)!r}; "
            "lookahead, lookbehind and backreferences are unsupported"
        )
    return None


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

    def validate_gather_spec_semantics(self, spec: dict[str, Any]) -> None:
        collect = spec.get("collect") if isinstance(spec, dict) else None
        if not isinstance(collect, dict):
            return
        for stage_name in ("list", "detail"):
            stage = collect.get(stage_name)
            fields = stage.get("fields") if isinstance(stage, dict) else None
            if not isinstance(fields, dict):
                continue
            for key, field in fields.items():
                if not isinstance(field, dict):
                    continue
                for transform in field.get("transforms") or []:
                    if isinstance(transform, dict) and transform.get("type") == "regex_extract":
                        error = re2_pattern_error(str(transform.get("pattern", "")))
                        if error:
                            raise SemanticContractError(f"collect.{stage_name}.fields.{key}: {error}")

    def gather_template(self) -> dict[str, Any]:
        return copy.deepcopy(self._gather_template)


def sha256_digest(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"
