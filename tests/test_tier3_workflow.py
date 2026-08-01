from deployment.recovery_api import RecoveryStore
from solvers.tier3_api import generate_suggestions


def recovery_with_tier3_option(store):
    recovery=store.create({"partition_id":"DEL","operator_id":"scheduler-1"})["recovery"]
    crews,legs=store._scenario_inputs()
    suggestion=generate_suggestions([legs[0]],[crews[0]],"DEL",recovery["state_version"])[0].to_dict()
    store._recoveries[recovery["id"]]["tier3"]={"status":"ready","unresolved_flight_ids":[legs[0].flight_id],"suggestions":[suggestion]}
    return store.get(recovery["id"]),suggestion


def test_scheduler_acceptance_creates_versioned_candidate_not_deployment_approval():
    store=RecoveryStore(); recovery,suggestion=recovery_with_tier3_option(store)
    result=store.decide_tier3_suggestion(recovery["id"],suggestion["suggestion_id"],{
        "state_version":recovery["state_version"],"action":"approve","operator_id":"scheduler-1",
        "correlation_id":"corr-tier3","causation_id":"cause-tier3",
    })["recovery"]
    candidate=next(item for item in result["candidates"] if item.get("source_suggestion_id")==suggestion["suggestion_id"])
    assert candidate["tier"]=="tier3"
    assert result["approvals"]==[]
    assert result["validated"] is False


def test_illegal_edit_is_rejected_and_state_is_preserved():
    store=RecoveryStore(); recovery,suggestion=recovery_with_tier3_option(store)
    try:
        store.decide_tier3_suggestion(recovery["id"],suggestion["suggestion_id"],{
            "state_version":recovery["state_version"],"action":"edit","operator_id":"scheduler-1",
            "crew_id":"SIM-002","flight_id":"AI421","reason":"Try an incompatible crew",
        })
    except Exception as exc:
        assert getattr(exc,"code",None)=="illegal_suggestion_edit"
    else:
        raise AssertionError("illegal Tier 3 edit was accepted")
    assert store.get(recovery["id"])["state_version"]==recovery["state_version"]


def test_hold_and_reject_require_reason():
    store=RecoveryStore(); recovery,suggestion=recovery_with_tier3_option(store)
    for action in ("hold","reject"):
        try:
            store.decide_tier3_suggestion(recovery["id"],suggestion["suggestion_id"],{
                "state_version":recovery["state_version"],"action":action,"operator_id":"scheduler-1",
            })
        except Exception as exc:
            assert getattr(exc,"code",None)=="reason_required"
        else:
            raise AssertionError(f"{action} without reason was accepted")
