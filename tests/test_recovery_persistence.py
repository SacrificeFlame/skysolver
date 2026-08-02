from deployment.recovery_api import RecoveryStore

def test_recovery_and_audit_survive_store_restart(tmp_path):
    path=tmp_path/"recovery.json";first=RecoveryStore(str(path));created=first.create({})["recovery"]
    second=RecoveryStore(str(path))
    assert second.get(created["id"])["state_version"]==1
    assert second.audit()[0]["action"]=="recovery_created"

def test_route_validation_calls_legality_layer():
    result=RecoveryStore().validate_route("AI421")
    assert result["ruleset_version"].startswith("dgca-car")
    assert set(result["checks"])=={"airport_sequence","positive_distance","arrival_after_departure"}

def test_solver_tier_metrics_are_executable():
    result=RecoveryStore().solver_tiers()
    assert result["data_mode"]=="executable-synthetic"
    assert [x["id"] for x in result["tiers"]]==["tier1","tier2","tier3"]
    assert result["tiers"][0]["elapsed_s"]>=0
