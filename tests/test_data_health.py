from datetime import datetime,timedelta,timezone
from integrations.health import DataHealthRegistry,SourceHealth,demo_registry


def source(name,**changes):
    now=datetime(2026,8,1,tzinfo=timezone.utc);values=dict(source_system=name,authoritative=True,required_for_solve=True,required_for_deployment=True,
        last_source_timestamp=now,last_ingested_at=now,max_freshness_seconds=60,contract_version="v1")
    values.update(changes);return SourceHealth(**values)


def test_all_required_authoritative_sources_must_be_fresh_and_reconciled():
    now=datetime(2026,8,1,tzinfo=timezone.utc);registry=DataHealthRegistry();registry.update(source("crew"));registry.update(source("aircraft"))
    result=registry.snapshot(now)
    assert result["solve_allowed"] and result["deployment_allowed"]


def test_stale_dead_letter_or_drift_blocks_deployment_and_solve():
    now=datetime(2026,8,1,tzinfo=timezone.utc);registry=DataHealthRegistry();registry.update(source("crew",last_ingested_at=now-timedelta(minutes=5),dead_letter_count=2,reconciliation_drift_count=1))
    result=registry.snapshot(now)
    assert not result["solve_allowed"] and not result["deployment_allowed"]
    assert {x["code"] for x in result["findings"]}=={"SOURCE_STALE","DEAD_LETTERS_PENDING","RECONCILIATION_DRIFT"}


def test_demo_fixture_allows_simulation_but_never_deployment():
    result=demo_registry().snapshot()
    assert result["solve_allowed"] is True and result["deployment_allowed"] is False
