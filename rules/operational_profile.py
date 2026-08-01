"""Operator-package-driven legality checks beyond a single assignment.

No limits in this module are represented as regulatory certification.  A
signed operator rules package supplies ``OperationalLimits`` in production.
The bundled defaults are conservative synthetic-test values.  Strict mode
fails closed when history or credential evidence required for arithmetic is
missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from core.domain import RuleViolation
from rules.engine import Assignment, CrewMember, RulesEngine


@dataclass(frozen=True)
class AccumulatedTotals:
    flight_minutes_28d: int
    flight_minutes_365d: int
    duty_minutes_7d: int
    duty_minutes_28d: int


@dataclass(frozen=True)
class OperationalLimits:
    package_reference: str
    flight_minutes_28d: int = 6000
    flight_minutes_365d: int = 60000
    duty_minutes_7d: int = 3600
    duty_minutes_28d: int = 11400
    maximum_consecutive_night_duties: int = 3
    maximum_standby_plus_duty_minutes: int = 1080
    minimum_approved_split_break_minutes: int = 180
    minimum_augmented_crew: int = 3
    accepted_rest_facility_classes: frozenset[str] = frozenset({"class-1", "class-2"})


@dataclass(frozen=True)
class OperationalContext:
    evaluated_at: datetime
    history_complete: bool
    accumulated: AccumulatedTotals | None = None
    licence_valid_until: datetime | None = None
    medical_valid_until: datetime | None = None
    recency_valid_until: datetime | None = None
    qualification_valid_until: Mapping[str, datetime] = field(default_factory=dict)
    acclimatized: bool | None = None
    timezone_delta_hours: float | None = None
    consecutive_night_duties: int | None = None
    standby_minutes_before_report: int = 0
    split_break_minutes: int = 0
    split_break_approved: bool = False
    augmented_crew_count: int = 0
    rest_facility_class: str | None = None
    required_roles: frozenset[str] = frozenset()
    assigned_roles: frozenset[str] = frozenset()
    visa_and_transit_allowed: bool | None = None
    operator_variation_reference: str | None = None

    def validate(self) -> None:
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        dated = [self.licence_valid_until, self.medical_valid_until, self.recency_valid_until,
                 *self.qualification_valid_until.values()]
        if any(value is not None and value.tzinfo is None for value in dated):
            raise ValueError("credential validity timestamps must be timezone-aware")
        numeric = [self.standby_minutes_before_report, self.split_break_minutes,
                   self.augmented_crew_count]
        if any(value < 0 for value in numeric):
            raise ValueError("operational context quantities cannot be negative")


class OperationalLegalityEvaluator:
    def __init__(self, limits: OperationalLimits):
        self.limits = limits

    @staticmethod
    def _finding(code: str, message: str, rule: str, crew_id: str, **details) -> RuleViolation:
        return RuleViolation(code, message, rule, entity_id=crew_id, details=details)

    @staticmethod
    def _minutes(assignment: Assignment) -> tuple[int, int]:
        duty = round((assignment.duty_end - assignment.duty_start).total_seconds() / 60)
        flight = round(sum((leg.scheduled_arr - leg.scheduled_dep).total_seconds() / 60
                           for leg in assignment.flight_legs if not leg.is_deadhead))
        return duty, flight

    def evaluate(self, crew: CrewMember, assignment: Assignment,
                 context: OperationalContext, strict: bool = True) -> list[RuleViolation]:
        context.validate()
        findings = list(RulesEngine.validate_assignment(crew, assignment))
        duty_minutes, flight_minutes = self._minutes(assignment)
        if strict and (not context.history_complete or context.accumulated is None):
            findings.append(self._finding("AUTHORITATIVE_HISTORY_REQUIRED",
                "Cumulative legality cannot be calculated without complete authoritative history",
                "OPERATOR-RULES-DATA-REQUIREMENT",crew.crew_id,history_complete=context.history_complete))
        elif context.accumulated is not None:
            findings.extend(self._cumulative(crew.crew_id,context.accumulated,duty_minutes,flight_minutes))
        findings.extend(self._credentials(crew,assignment,context,strict))
        findings.extend(self._acclimatization_and_nights(crew,assignment,context,strict))
        findings.extend(self._standby_split_augmentation(crew,assignment,context,duty_minutes))
        missing_roles=context.required_roles-context.assigned_roles
        if missing_roles:
            findings.append(self._finding("CREW_COMPLEMENT_INCOMPLETE",
                "Required crew roles are not assigned","OPERATOR-COMPLEMENT",crew.crew_id,
                required=sorted(context.required_roles),assigned=sorted(context.assigned_roles),
                missing=sorted(missing_roles)))
        if context.visa_and_transit_allowed is False:
            findings.append(self._finding("IMMIGRATION_INFEASIBLE",
                "Visa or transit requirements are not satisfied","IMMIGRATION-POLICY",crew.crew_id))
        elif strict and context.visa_and_transit_allowed is None:
            findings.append(self._finding("IMMIGRATION_EVIDENCE_REQUIRED",
                "Visa and transit eligibility has not been verified","IMMIGRATION-POLICY",crew.crew_id))
        return findings

    def _cumulative(self,crew_id: str, totals: AccumulatedTotals,
                    duty: int, flight: int) -> list[RuleViolation]:
        checks=(
            ("CUMULATIVE_FLIGHT_28D",totals.flight_minutes_28d+flight,self.limits.flight_minutes_28d,"flight_minutes_28d"),
            ("CUMULATIVE_FLIGHT_365D",totals.flight_minutes_365d+flight,self.limits.flight_minutes_365d,"flight_minutes_365d"),
            ("CUMULATIVE_DUTY_7D",totals.duty_minutes_7d+duty,self.limits.duty_minutes_7d,"duty_minutes_7d"),
            ("CUMULATIVE_DUTY_28D",totals.duty_minutes_28d+duty,self.limits.duty_minutes_28d,"duty_minutes_28d"),
        )
        return [self._finding(code,f"Projected {field} {actual}m exceeds {limit}m",
            self.limits.package_reference,crew_id,actual_minutes=actual,limit_minutes=limit,
            formula="prior_minutes + proposed_assignment_minutes")
            for code,actual,limit,field in checks if actual>limit]

    def _credentials(self,crew: CrewMember,assignment: Assignment,context: OperationalContext,
                     strict: bool) -> list[RuleViolation]:
        out=[]; required={leg.aircraft_type.replace("neo","") for leg in assignment.flight_legs if not leg.is_deadhead}
        credentials={"LICENCE":context.licence_valid_until,"MEDICAL":context.medical_valid_until,
                     "RECENCY":context.recency_valid_until}
        for name,valid_until in credentials.items():
            if valid_until is None and strict:
                out.append(self._finding(f"{name}_EVIDENCE_REQUIRED",f"{name.title()} validity is unavailable",
                    "OPERATOR-CREDENTIALS",crew.crew_id))
            elif valid_until is not None and valid_until<assignment.duty_end:
                out.append(self._finding(f"{name}_EXPIRED",f"{name.title()} expires before duty release",
                    "OPERATOR-CREDENTIALS",crew.crew_id,valid_until=valid_until.isoformat(),
                    duty_end=assignment.duty_end.isoformat()))
        for qualification in sorted(required):
            valid_until=context.qualification_valid_until.get(qualification)
            if valid_until is None and strict:
                out.append(self._finding("QUALIFICATION_VALIDITY_REQUIRED",
                    f"Validity evidence for {qualification} is unavailable","OPERATOR-QUALIFICATION",
                    crew.crew_id,qualification=qualification))
            elif valid_until is not None and valid_until<assignment.duty_end:
                out.append(self._finding("QUALIFICATION_EXPIRED",f"{qualification} expires before duty release",
                    "OPERATOR-QUALIFICATION",crew.crew_id,qualification=qualification,
                    valid_until=valid_until.isoformat()))
        return out

    def _acclimatization_and_nights(self,crew: CrewMember,assignment: Assignment,
                                    context: OperationalContext,strict: bool) -> list[RuleViolation]:
        out=[];night=2<=assignment.duty_start.hour<6
        if context.acclimatized is None and strict:
            out.append(self._finding("ACCLIMATIZATION_EVIDENCE_REQUIRED",
                "Acclimatization state is required to select the applicable FDP table",
                self.limits.package_reference,crew.crew_id,timezone_delta_hours=context.timezone_delta_hours))
        if night:
            if context.consecutive_night_duties is None and strict:
                out.append(self._finding("NIGHT_HISTORY_REQUIRED",
                    "Consecutive-night history is unavailable",self.limits.package_reference,crew.crew_id))
            elif context.consecutive_night_duties is not None:
                projected=context.consecutive_night_duties+1
                if projected>self.limits.maximum_consecutive_night_duties:
                    out.append(self._finding("CONSECUTIVE_NIGHT_LIMIT",
                        f"Projected consecutive night duties {projected} exceeds {self.limits.maximum_consecutive_night_duties}",
                        self.limits.package_reference,crew.crew_id,actual=projected,
                        limit=self.limits.maximum_consecutive_night_duties))
        return out

    def _standby_split_augmentation(self,crew: CrewMember,assignment: Assignment,
                                    context: OperationalContext,duty_minutes: int) -> list[RuleViolation]:
        out=[];combined=context.standby_minutes_before_report+duty_minutes
        if combined>self.limits.maximum_standby_plus_duty_minutes:
            out.append(self._finding("STANDBY_PLUS_DUTY_LIMIT",
                f"Standby plus duty {combined}m exceeds {self.limits.maximum_standby_plus_duty_minutes}m",
                self.limits.package_reference,crew.crew_id,standby_minutes=context.standby_minutes_before_report,
                duty_minutes=duty_minutes,limit_minutes=self.limits.maximum_standby_plus_duty_minutes))
        if context.split_break_minutes:
            if not context.split_break_approved or context.split_break_minutes<self.limits.minimum_approved_split_break_minutes:
                out.append(self._finding("SPLIT_DUTY_NOT_CREDITABLE",
                    "Split-duty break is not approved or is below the package minimum",
                    self.limits.package_reference,crew.crew_id,break_minutes=context.split_break_minutes,
                    approved=context.split_break_approved,
                    minimum_minutes=self.limits.minimum_approved_split_break_minutes))
        if context.augmented_crew_count:
            if context.augmented_crew_count<self.limits.minimum_augmented_crew:
                out.append(self._finding("AUGMENTED_COMPLEMENT_INSUFFICIENT",
                    "Augmented operation has insufficient qualified complement",self.limits.package_reference,
                    crew.crew_id,actual=context.augmented_crew_count,limit=self.limits.minimum_augmented_crew))
            if context.rest_facility_class not in self.limits.accepted_rest_facility_classes:
                out.append(self._finding("INFLIGHT_REST_FACILITY_INELIGIBLE",
                    "Rest facility is not approved for augmented-operation credit",self.limits.package_reference,
                    crew.crew_id,facility_class=context.rest_facility_class,
                    accepted=sorted(self.limits.accepted_rest_facility_classes)))
        return out
