"""Certification evidence gate and explicitly non-certifying development replay.

This module intentionally separates measurements from certification. A small or
partially simulated replay can be useful to developers, but can never become an
airline safety claim through a convenient label or a hard-coded profile name.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime

from data.generate import generate_crew_pool, generate_flight_legs, partition_by_hub
from solvers.tier1 import solve_partition
from solvers.tier3_api import generate_suggestions


CERTIFIED_MINIMUM_FLIGHT_RECORDS = 50_100
TIER1_LIMIT_SECONDS = 300.0


@dataclass(frozen=True)
class CertificationEvidence:
    affected_flight_records: int
    solvable_cases: int
    legal_tier1_cases: int
    tier1_elapsed_seconds: float
    passenger_recovery_computed: bool = False
    tier3_generated: bool = False
    contention_exercised: bool = False
    worker_loss_exercised: bool = False
    regional_failover_exercised: bool = False
    illegal_assignments_accepted: int = 0


@dataclass(frozen=True)
class CertificationResult:
    status: str
    blockers: tuple[str, ...]
    evidence: CertificationEvidence

    def to_dict(self) -> dict:
        return {"status": self.status, "blockers": list(self.blockers), "evidence": asdict(self.evidence)}


def evaluate_certification_evidence(evidence: CertificationEvidence) -> CertificationResult:
    blockers: list[str] = []
    if evidence.affected_flight_records < CERTIFIED_MINIMUM_FLIGHT_RECORDS:
        blockers.append("minimum_flight_volume_not_met")
    if not evidence.passenger_recovery_computed:
        blockers.append("passenger_recovery_not_computed")
    if not evidence.tier3_generated:
        blockers.append("tier3_not_generated")
    if not evidence.contention_exercised:
        blockers.append("database_broker_adapter_contention_not_exercised")
    if not evidence.worker_loss_exercised:
        blockers.append("worker_loss_not_exercised")
    if not evidence.regional_failover_exercised:
        blockers.append("regional_failover_not_exercised")
    if evidence.solvable_cases != evidence.legal_tier1_cases:
        blockers.append("tier1_legal_coverage_below_100_percent")
    if evidence.tier1_elapsed_seconds > TIER1_LIMIT_SECONDS:
        blockers.append("tier1_time_limit_exceeded")
    if evidence.illegal_assignments_accepted:
        blockers.append("illegal_assignment_accepted")
    return CertificationResult(
        status="NOT_CERTIFIED" if blockers else "CERTIFICATION_EVIDENCE_ACCEPTED",
        blockers=tuple(blockers),
        evidence=evidence,
    )


def run_development_replay(*, crew_count: int = 2_000, flight_count: int = 800) -> CertificationResult:
    """Exercise real Tier 1 and Tier 3 code without claiming production scale."""
    baseline = datetime(2026, 1, 15)
    crew = generate_crew_pool(crew_count, baseline, seed=42)
    flights = generate_flight_legs(flight_count, baseline, seed=123)
    partitions = partition_by_hub(crew, flights)
    started = time.monotonic()
    legal_cases = 0
    unresolved = []
    tier3_count = 0
    for partition, (partition_crew, partition_flights) in partitions.items():
        result = solve_partition(partition_crew, partition_flights, time_budget_s=1.0)
        legal_cases += len(partition_flights) - len(result.uncovered)
        unresolved.extend(result.uncovered)
        tier3_count += len(generate_suggestions(result.uncovered, partition_crew, partition))
    elapsed = time.monotonic() - started
    evidence = CertificationEvidence(
        affected_flight_records=len(flights),
        solvable_cases=len(flights),
        legal_tier1_cases=legal_cases,
        tier1_elapsed_seconds=elapsed,
        tier3_generated=(not unresolved or tier3_count > 0),
    )
    return evaluate_certification_evidence(evidence)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crew", type=int, default=2_000)
    parser.add_argument("--flights", type=int, default=800)
    parser.add_argument("--require-certification", action="store_true")
    args = parser.parse_args()
    result = run_development_replay(crew_count=args.crew, flight_count=args.flights)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 1 if args.require_certification and result.status != "CERTIFICATION_EVIDENCE_ACCEPTED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
