"""Predictive disruption risk and solver pre-scaling recommendations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import math


@dataclass(frozen=True)
class DisruptionSignal:
    signal_id: str
    source: str
    issued_at: datetime
    expected_start: datetime
    expected_end: datetime
    confidence: float
    severity: float
    affected_airports: tuple[str, ...]
    forecast_affected_flights: int


@dataclass(frozen=True)
class PairingForecast:
    pairing_id: str
    crew_id: str
    airports: tuple[str, ...]
    duty_start: datetime
    duty_end: datetime
    remaining_duty_minutes: int
    connection_buffer_minutes: int


@dataclass(frozen=True)
class PairingRisk:
    pairing_id: str
    crew_id: str
    score: float
    level: str
    reasons: tuple[str, ...]


class PrestagePlanner:
    def __init__(self, flights_per_worker_per_minute: float = 4.0, response_window_minutes: int = 5):
        if flights_per_worker_per_minute <= 0 or response_window_minutes <= 0:
            raise ValueError("Prestage capacity assumptions must be positive")
        self.throughput = flights_per_worker_per_minute
        self.response_window = response_window_minutes

    def plan(self, signal: DisruptionSignal, pairings: list[PairingForecast], current_workers: int) -> dict:
        if signal.issued_at.tzinfo is None or signal.expected_start.tzinfo is None or signal.expected_end.tzinfo is None:
            raise ValueError("Disruption signal timestamps must be timezone-aware")
        if not 0 <= signal.confidence <= 1 or not 0 <= signal.severity <= 1:
            raise ValueError("Signal confidence and severity must be within [0,1]")
        if signal.expected_end <= signal.expected_start:
            raise ValueError("Signal expected period must be positive")
        weighted_volume = signal.forecast_affected_flights * max(0.1, signal.confidence) * max(0.1, signal.severity)
        required_workers = max(1, math.ceil(weighted_volume / (self.throughput * self.response_window)))
        risks = [risk for pairing in pairings if (risk := self._pairing_risk(signal, pairing)) is not None]
        risks.sort(key=lambda item: (-item.score, item.pairing_id))
        lead_minutes = (signal.expected_start - signal.issued_at).total_seconds() / 60
        return {
            "signal_id": signal.signal_id,
            "source": signal.source,
            "recommended_workers": required_workers,
            "additional_workers": max(0, required_workers - current_workers),
            "scale_by": (signal.expected_start - timedelta(minutes=max(10, min(60, lead_minutes / 2)))).isoformat(),
            "forecast_weighted_volume": round(weighted_volume, 2),
            "at_risk_pairings": [asdict(item) for item in risks],
            "authoritative": False,
            "decision": "recommendation_only",
        }

    @staticmethod
    def _pairing_risk(signal: DisruptionSignal, pairing: PairingForecast) -> PairingRisk | None:
        intersects_airport = bool(set(pairing.airports) & set(signal.affected_airports))
        overlaps_time = pairing.duty_end >= signal.expected_start and pairing.duty_start <= signal.expected_end
        if not intersects_airport or not overlaps_time:
            return None
        expected_delay = int(180 * signal.severity * signal.confidence)
        duty_exposure = max(0, expected_delay - pairing.remaining_duty_minutes)
        connection_exposure = max(0, expected_delay - pairing.connection_buffer_minutes)
        score = min(100.0, signal.severity * 35 + signal.confidence * 20 + min(25, duty_exposure / 4) + min(20, connection_exposure / 3))
        reasons = ["Pairing intersects forecast disruption airport and time window"]
        if duty_exposure: reasons.append(f"Forecast delay exceeds remaining duty buffer by {duty_exposure} minutes")
        if connection_exposure: reasons.append(f"Forecast delay exceeds connection buffer by {connection_exposure} minutes")
        level = "critical" if score >= 75 else "high" if score >= 50 else "watch"
        return PairingRisk(pairing.pairing_id, pairing.crew_id, round(score, 1), level, tuple(reasons))
