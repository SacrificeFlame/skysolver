"""Separately deployable legality execution surface.

This service is deliberately package-driven. It does not call an optimizer and
does not accept a client assertion that a rules package is certified. The
configured execution context determines assurance and certificate eligibility.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from rules.certificates import CertificateIssuer
from rules.engine import Assignment, CrewMember, FlightLeg, Qualification, RulesEngine


class CrewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crew_id: str
    base_hub: str
    current_location: str
    qualifications: list[str]
    last_rest_end: datetime | None = None


class LegInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flight_id: str
    origin: str
    destination: str
    scheduled_dep: datetime
    scheduled_arr: datetime
    aircraft_type: str
    is_deadhead: bool = False


class AssignmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crew_id: str
    duty_start: datetime
    duty_end: datetime
    flight_legs: list[LegInput] = Field(min_length=1)


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    recovery_id: str
    candidate_id: str
    state_version: int = Field(ge=1)
    input_snapshot_id: str
    crew: list[CrewInput]
    assignments: list[AssignmentInput]
    candidate_artifact: dict[str, Any]


@dataclass(frozen=True)
class RulesExecutionContext:
    package_id: str
    ruleset_version: str
    package_sha256: str
    status: str
    assurance_level: str
    execution_identity: str
    service_version: str

    @property
    def certificate_eligible(self) -> bool:
        return self.status == "active" and self.assurance_level == "operator_approved_certified"


def _trace(violation: dict[str, Any]) -> dict[str, Any]:
    details = violation.get("details") or {}
    return {
        "rule_reference": violation["rule_ref"],
        "result": "failed",
        "entity_id": violation.get("entity_id"),
        "inputs": details,
        "calculation": violation["message"],
        "finding_code": violation["code"],
    }


class ValidationExecutor:
    def __init__(self, context: RulesExecutionContext, issuer: CertificateIssuer | None = None):
        self.context = context
        self.issuer = issuer

    def validate(self, request: ValidationRequest) -> dict[str, Any]:
        crew_by_id = {}
        for item in request.crew:
            try:
                qualifications = {Qualification[value.replace("neo", "")] for value in item.qualifications}
            except KeyError as exc:
                raise ValueError(f"Unknown qualification {exc.args[0]}") from exc
            crew_by_id[item.crew_id] = CrewMember(
                item.crew_id, item.base_hub, qualifications,
                current_location=item.current_location, last_rest_end=item.last_rest_end,
            )
        findings: list[dict[str, Any]] = []
        for stored in request.assignments:
            if stored.crew_id not in crew_by_id:
                raise ValueError(f"Assignment references missing crew {stored.crew_id}")
            legs = [FlightLeg(**item.model_dump()) for item in stored.flight_legs]
            assignment = Assignment(stored.crew_id, legs, stored.duty_start, stored.duty_end)
            findings.extend(item.to_dict() for item in RulesEngine.validate_assignment(crew_by_id[stored.crew_id], assignment))
        response = {
            "valid": not findings,
            "findings": findings,
            "calculation_trace": [_trace(item) for item in findings],
            "rules_execution": asdict(self.context),
            "certificate": None,
            "warning": None if self.context.certificate_eligible else "Rules execution is not operator-approved or certified",
        }
        if not findings and self.context.certificate_eligible:
            if self.issuer is None:
                raise RuntimeError("Certified execution context has no certificate issuer")
            rules_package = {
                "package_id": self.context.package_id,
                "ruleset_version": self.context.ruleset_version,
                "package_sha256": self.context.package_sha256,
            }
            certificate = self.issuer.issue(
                tenant_id=request.tenant_id, recovery_id=request.recovery_id,
                candidate_id=request.candidate_id, input_snapshot=request.model_dump(mode="json"),
                candidate=request.candidate_artifact, rules_package=rules_package,
                ruleset_version=self.context.ruleset_version, state_version=request.state_version, findings=[],
            )
            response["certificate"] = certificate.to_dict()
        return response


def create_validation_app(executor: ValidationExecutor) -> FastAPI:
    app = FastAPI(title="SkySolver Legality Validation Service", version=executor.context.service_version)

    @app.get("/health/live")
    def live():
        return {"status": "live"}

    @app.get("/health/ready")
    def ready():
        return {
            "status": "ready", "ruleset_version": executor.context.ruleset_version,
            "assurance_level": executor.context.assurance_level,
            "certificate_eligible": executor.context.certificate_eligible,
        }

    @app.post("/v1/validate")
    def validate(request: ValidationRequest):
        try:
            return executor.validate(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_validation_input", "message": str(exc)}) from exc

    return app


DEMO_CONTEXT = RulesExecutionContext(
    package_id="demo-dgca-oriented", ruleset_version=RulesEngine.RULESET_VERSION,
    package_sha256="0" * 64, status="demo", assurance_level="demo_in_process_not_certified",
    execution_identity="validation-demo-process", service_version="2026.08-demo",
)
app = create_validation_app(ValidationExecutor(DEMO_CONTEXT))
