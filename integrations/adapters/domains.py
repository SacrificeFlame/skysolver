"""Canonical capability declarations for carrier adapter implementations."""

from integrations.adapters.base import AdapterCapabilities


SCHEDULE = AdapterCapabilities("schedule-system", frozenset({"schedule.v1"}), frozenset())
CREW = AdapterCapabilities("crew-operations", frozenset({"crew.v1", "pairing.v1"}),
                           frozenset({"publish_assignment", "publish_deadhead"}))
AIRCRAFT = AdapterCapabilities("aircraft-operations", frozenset({"aircraft.v1", "rotation.v1"}),
                               frozenset({"publish_rotation", "publish_swap"}))
AODB = AdapterCapabilities("airport-aodb", frozenset({"gate.v1", "airport-resource.v1"}),
                           frozenset({"publish_gate"}))
PASSENGER = AdapterCapabilities("passenger-service", frozenset({"passenger.v1", "inventory.v1"}),
                                frozenset({"publish_reaccommodation", "publish_notification"}))
