"""
SkySolver v2 - Predictive Pre-Staging

Ingests weather/disruption signals to pre-scale compute and flag at-risk
crew pairings before disruption volume spikes - not only after duty-time
violations start cascading.

This is Requirement #6 from the brief: "Predictive pre-staging."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Tuple
from enum import Enum
import json


class DisruptionType(Enum):
    WEATHER = "weather"
    STAFFING = "staffing"
    AIRPORT_CLOSURE = "airport_closure"
    AIRSPACE = "airspace"


class Severity(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class DisruptionSignal:
    """A weather/disruption signal from external source."""
    signal_id: str
    type: DisruptionType
    severity: Severity
    affected_hubs: List[str]
    start_time: datetime
    end_time: datetime
    confidence: float  # 0-1
    description: str

    def to_dict(self) -> Dict:
        return {
            "signal_id": self.signal_id,
            "type": self.type.value,
            "severity": self.severity.value,
            "affected_hubs": self.affected_hubs,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "confidence": self.confidence,
            "description": self.description,
        }


@dataclass
class PreStageAction:
    """Recommended pre-staging action."""
    hub: str
    recommended_workers: int
    reason: str
    priority: int  # 1 = highest

    def to_dict(self) -> Dict:
        return {
            "hub": self.hub,
            "recommended_workers": self.recommended_workers,
            "reason": self.reason,
            "priority": self.priority,
        }


@dataclass
class AtRiskPairing:
    """A crew pairing flagged as at-risk before disruption."""
    crew_id: str
    hub: str
    risk_score: float  # 0-1
    reason: str

    def to_dict(self) -> Dict:
        return {
            "crew_id": self.crew_id,
            "hub": self.hub,
            "risk_score": self.risk_score,
            "reason": self.reason,
        }


class PredictivePreStager:
    """
    Analyzes disruption signals and recommends pre-staging actions.

    Uses simple heuristics + threshold-based triggering. Production would
    use ML for better prediction.
    """

    # Worker scaling formula: base + severity_factor * affected_flights_estimate
    BASE_WORKERS = 3
    SEVERITY_WORKER_MULTIPLIER = {
        Severity.LOW: 1,
        Severity.MEDIUM: 2,
        Severity.HIGH: 4,
        Severity.CRITICAL: 8,
    }
    # Estimated flights affected per hub per severity level
    EST_FLIGHTS_PER_HUB = {
        Severity.LOW: 20,
        Severity.MEDIUM: 100,
        Severity.HIGH: 500,
        Severity.CRITICAL: 1500,
    }

    def __init__(self, confidence_threshold: float = 0.6):
        self.confidence_threshold = confidence_threshold

    def ingest_signal(self, signal: DisruptionSignal) -> List[PreStageAction]:
        """
        Ingest a disruption signal and produce pre-staging recommendations.

        Returns list of recommended actions (empty if confidence too low).
        """
        if signal.confidence < self.confidence_threshold:
            return []  # Don't pre-stage on low-confidence signals

        actions: List[PreStageAction] = []

        for hub in signal.affected_hubs:
            # Estimate affected flights
            est_flights = self.EST_FLIGHTS_PER_HUB[signal.severity]
            # Scale workers: base + multiplier * (flights / 100)
            workers = self.BASE_WORKERS + int(
                self.SEVERITY_WORKER_MULTIPLIER[signal.severity]
                * (est_flights / 100.0)
            )
            workers = min(workers, 50)  # Cap at 50 per hub

            actions.append(PreStageAction(
                hub=hub,
                recommended_workers=workers,
                reason=f"{signal.type.value} severity {signal.severity.name} "
                       f"(conf: {signal.confidence:.0%})",
                priority=signal.severity.value,
            ))

        # Sort by priority (highest first)
        actions.sort(key=lambda a: a.priority, reverse=True)
        return actions

    def flag_at_risk_pairings(
        self,
        signal: DisruptionSignal,
        crew_pool: List[any],  # CrewMember from rules.engine
    ) -> List[AtRiskPairing]:
        """
        Flag crew pairings at risk before disruption hits.

        Uses heuristics:
        - Crew at affected hubs are higher risk
        - Crew with tight rest margins are higher risk
        - Crew with limited qualifications are harder to reassign (higher risk)
        """
        at_risk: List[AtRiskPairing] = []

        for crew in crew_pool:
            if crew.base_hub not in signal.affected_hubs:
                continue

            risk = 0.0
            reasons = []

            # Risk factor 1: Hub is in disruption path
            risk += 0.3
            reasons.append("based at affected hub")

            # Risk factor 2: Tight rest margin (last_rest_end recent)
            if crew.last_rest_end:
                hours_since_rest = (
                    signal.start_time - crew.last_rest_end
                ).total_seconds() / 3600.0
                if hours_since_rest < 12:
                    risk += 0.3
                    reasons.append("tight rest margin")
                elif hours_since_rest < 10:
                    risk += 0.5
                    reasons.append("insufficient rest buffer")

            # Risk factor 3: Limited qualifications = harder to reassign
            if len(crew.qualifications) <= 1:
                risk += 0.2
                reasons.append("single qualification")

            # Risk factor 4: Disruption severity
            risk += 0.1 * signal.severity.value

            if risk > 0.5:
                at_risk.append(AtRiskPairing(
                    crew_id=crew.crew_id,
                    hub=crew.base_hub,
                    risk_score=min(risk, 1.0),
                    reason="; ".join(reasons),
                ))

        # Sort by risk descending
        at_risk.sort(key=lambda p: p.risk_score, reverse=True)
        return at_risk

    def generate_prestage_plan(
        self,
        signals: List[DisruptionSignal],
        crew_pool: List[any],
    ) -> Dict:
        """
        Generate complete pre-staging plan from multiple signals.

        Returns dict with actions and at-risk pairings.
        """
        all_actions: List[PreStageAction] = []
        all_at_risk: List[AtRiskPairing] = []

        for signal in signals:
            actions = self.ingest_signal(signal)
            all_actions.extend(actions)

            pairings = self.flag_at_risk_pairings(signal, crew_pool)
            all_at_risk.extend(pairings)

        # Aggregate worker counts per hub
        hub_workers: Dict[str, int] = {}
        for a in all_actions:
            hub_workers[a.hub] = max(hub_workers.get(a.hub, 0), a.recommended_workers)

        aggregated_actions = [
            PreStageAction(hub=h, recommended_workers=w, reason="Aggregated from signals", priority=1)
            for h, w in sorted(hub_workers.items(), key=lambda x: x[1], reverse=True)
        ]

        return {
            "pre_stage_actions": [a.to_dict() for a in aggregated_actions],
            "at_risk_pairings": [p.to_dict() for p in all_at_risk],
            "total_hubs": len(aggregated_actions),
            "total_at_risk_crew": len(all_at_risk),
            "generated_at": datetime.now().isoformat(),
        }


# ----------------------------------------------------------------------
# SIGNAL SOURCE (Synthetic - No real airline data)
# ----------------------------------------------------------------------

def generate_severe_monsoon_signal(base_time: datetime) -> DisruptionSignal:
    """
    Generate a synthetic severe Indian monsoon disruption signal.

    NOT real data - synthetic for testing only.
    """
    return DisruptionSignal(
        signal_id="SYNTH_INDIA_MONSOON",
        type=DisruptionType.WEATHER,
        severity=Severity.CRITICAL,
        affected_hubs=["DEL", "BOM", "BLR", "HYD", "CCU", "MAA", "COK"],
        start_time=base_time,
        end_time=base_time + timedelta(hours=72),
        confidence=0.85,
        description="Synthetic multi-day monsoon and flow-control disruption",
    )


def generate_mild_signal(base_time: datetime) -> DisruptionSignal:
    """Generate a mild synthetic disruption signal."""
    return DisruptionSignal(
        signal_id="SYNTH_MILD_001",
        type=DisruptionType.WEATHER,
        severity=Severity.MEDIUM,
        affected_hubs=["SEA", "PHX"],
        start_time=base_time + timedelta(hours=6),
        end_time=base_time + timedelta(hours=18),
        confidence=0.7,
        description="Synthetic regional rain event",
    )


if __name__ == "__main__":
    from datetime import datetime
    from data.generate import generate_crew_pool

    prestager = PredictivePreStager()
    baseline = datetime(2024, 1, 15)

    signals = [generate_severe_monsoon_signal(baseline), generate_mild_signal(baseline)]
    crew = generate_crew_pool(500, baseline)

    plan = prestager.generate_prestage_plan(signals, crew)

    print("Pre-Staging Plan:")
    print(f"  Hubs to pre-stage: {plan['total_hubs']}")
    print(f"  At-risk crew flagged: {plan['total_at_risk_crew']}")
    print("\nActions:")
    for a in plan["pre_stage_actions"][:5]:
        print(f"  {a['hub']}: {a['recommended_workers']} workers (priority {a['priority']})")
    print("\nTop at-risk pairings:")
    for p in plan["at_risk_pairings"][:5]:
        print(f"  {p['crew_id']} @ {p['hub']}: risk {p['risk_score']:.2f}")
