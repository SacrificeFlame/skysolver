from datetime import datetime, timedelta, timezone

from core.prestage import DisruptionSignal, PairingForecast, PrestagePlanner


def test_weather_signal_recommends_workers_before_event_and_flags_pairings():
    issued = datetime(2026, 8, 1, 1, tzinfo=timezone.utc); start = issued + timedelta(hours=2)
    signal = DisruptionSignal("WX-DEL-1", "IMD-adapter", issued, start, start + timedelta(hours=6), .9, .8, ("DEL",), 500)
    pairings = [PairingForecast("P1", "IC-184", ("DEL", "BOM"), start - timedelta(hours=1), start + timedelta(hours=4), 45, 30)]
    result = PrestagePlanner().plan(signal, pairings, current_workers=3)
    assert result["recommended_workers"] > 3
    assert datetime.fromisoformat(result["scale_by"]) < start
    assert result["at_risk_pairings"][0]["level"] in {"high", "critical"}
    assert result["decision"] == "recommendation_only"


def test_unaffected_pairing_is_not_flagged():
    current = datetime(2026, 8, 1, tzinfo=timezone.utc)
    signal = DisruptionSignal("WX-1", "fixture", current, current + timedelta(hours=1), current + timedelta(hours=3), .8, .7, ("DEL",), 50)
    pairing = PairingForecast("P1", "C1", ("BLR", "MAA"), current, current + timedelta(hours=2), 200, 90)
    assert PrestagePlanner().plan(signal, [pairing], 2)["at_risk_pairings"] == []


def test_worker_demand_scales_with_volume_without_batch_cap():
    current = datetime(2026, 8, 1, tzinfo=timezone.utc)
    small = DisruptionSignal("S", "fixture", current, current + timedelta(hours=1), current + timedelta(hours=2), 1, 1, ("DEL",), 100)
    large = DisruptionSignal("L", "fixture", current, current + timedelta(hours=1), current + timedelta(hours=2), 1, 1, ("DEL",), 1000)
    planner = PrestagePlanner(flights_per_worker_per_minute=5, response_window_minutes=5)
    assert planner.plan(large, [], 0)["recommended_workers"] == 10 * planner.plan(small, [], 0)["recommended_workers"]
