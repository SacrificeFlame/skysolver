from deployment.recovery_api import RecoveryStore


def test_boot_recovery_escalates_one_case_and_tier3_completes_the_plan(tmp_path):
    store = RecoveryStore(state_path=tmp_path / "demo-state.json")
    created = store.create({"disruption_id": "DSP-DEL-0726", "partition_id": "DEL"})
    recovery = created["recovery"]

    assert recovery["progress"] == 80
    assert recovery["status"] == "awaiting_intervention"
    assert recovery["tier3"]["status"] == "ready"
    assert recovery["tier3"]["unresolved_flight_ids"] == ["UK945"]
    assert recovery["tier3"]["suggestions"]

    suggestion = recovery["tier3"]["suggestions"][0]
    completed = store.decide_tier3_suggestion(
        recovery["id"],
        suggestion["suggestion_id"],
        {
            "action": "approve",
            "reason": "Scheduler accepts the legal captain recovery option",
            "state_version": recovery["state_version"],
            "operator_id": "scheduler-demo",
        },
    )["recovery"]

    assert completed["progress"] == 100
    assert completed["stage"] == "candidate_comparison"
    assert completed["candidates"][-1]["tier"] == "tier3"
    assert completed["candidates"][-1]["coverage"] == 1
    assert completed["candidates"][-1]["recommended"] is True
