from datetime import datetime

import pytest

from state.event_store import ConcurrencyError, EventStore, create_crew_event, flight_assigned_event


def test_append_is_idempotent_and_sequence_is_monotonic():
    store = EventStore()
    created = create_crew_event("C1", "DEN", "DEN", {"B737"}, timestamp=datetime(2024, 1, 1))
    assert store.append(created, expected_version=0) is True
    assert store.append(created) is False
    assigned = flight_assigned_event("C1", "DEN", "F1", "LAX", datetime(2024, 1, 1, 1))
    assert store.append(assigned, expected_version=1) is True
    assert [e.sequence for e in store.get_crew_events("C1", "DEN")] == [1, 2]


def test_stale_writer_is_rejected():
    store = EventStore()
    store.append(create_crew_event("C1", "DEN", "DEN", set()))
    with pytest.raises(ConcurrencyError):
        store.append(flight_assigned_event("C1", "DEN", "F1", "LAX"), expected_version=0)


def test_serialized_stream_replays_with_metadata(tmp_path):
    store = EventStore()
    store.append(create_crew_event("C1", "DEN", "DEN", {"B737"}))
    path = tmp_path / "events.json"
    store.serialize(str(path))
    loaded = EventStore.deserialize(str(path))
    event = next(loaded.get_partition_stream("DEN"))
    assert event.sequence == 1 and event.correlation_id
