from datetime import datetime, timedelta, timezone

import pytest

from core.resource_holds import HoldConflict, ResourceHoldRegistry


def test_hold_acquisition_is_atomic_and_blocks_double_booking():
    registry = ResourceHoldRegistry()
    first = registry.acquire(tenant_id="airline", recovery_id="R1", candidate_id="C1", candidate_version=2,
                             resources=["crew:C1", "tail:VT-EXA"], owner="scheduler-1")
    with pytest.raises(HoldConflict) as conflict:
        registry.acquire(tenant_id="airline", recovery_id="R2", candidate_id="C2", candidate_version=1,
                         resources=["tail:VT-EXA", "gate:DEL-42"], owner="scheduler-2")
    assert conflict.value.code == "resource_conflict"
    assert conflict.value.resources == ["tail:VT-EXA"]
    assert registry.get(first.hold_id).candidate_id == "C1"


def test_expired_hold_releases_resources():
    current = datetime(2026, 8, 1, tzinfo=timezone.utc)
    registry = ResourceHoldRegistry(clock=lambda: current)
    hold = registry.acquire(tenant_id="airline", recovery_id="R1", candidate_id="C1", candidate_version=1,
                            resources=["crew:C1"], owner="scheduler", ttl_seconds=30)
    current += timedelta(seconds=31)
    with pytest.raises(HoldConflict, match="expired"):
        registry.get(hold.hold_id)
    replacement = registry.acquire(tenant_id="airline", recovery_id="R2", candidate_id="C2", candidate_version=1,
                                   resources=["crew:C1"], owner="scheduler-2", ttl_seconds=30)
    assert replacement.candidate_id == "C2"


def test_hold_is_bound_to_exact_candidate_version():
    registry = ResourceHoldRegistry()
    hold = registry.acquire(tenant_id="airline", recovery_id="R1", candidate_id="C1", candidate_version=3,
                            resources=["crew:C1"], owner="scheduler")
    with pytest.raises(HoldConflict) as stale:
        registry.assert_current(hold.hold_id, "C1", 4)
    assert stale.value.code == "stale_hold"


def test_only_owner_can_release_hold():
    registry = ResourceHoldRegistry()
    hold = registry.acquire(tenant_id="airline", recovery_id="R1", candidate_id="C1", candidate_version=1,
                            resources=["crew:C1"], owner="scheduler")
    with pytest.raises(HoldConflict) as denied:
        registry.release(hold.hold_id, "another-scheduler")
    assert denied.value.code == "hold_owner_mismatch"
