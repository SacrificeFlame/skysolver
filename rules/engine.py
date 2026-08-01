"""Independent DGCA flight-duty and qualification legality layer.

This demonstrator implements the prescriptive checks needed by every solver
tier against DGCA CAR Section 7, Series J, Part III (Issue III, Rev. 1,
8 January 2024). It is deliberately conservative and does not claim to replace
an operator-approved FDTL scheme or FRMS.
"""

from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from core.domain import RuleViolation


class Qualification(Enum):
    B737="B737"; B777="B777"; A320="A320"; A321="A321"; B787="B787"
    NIGHT_FLYING="NIGHT_FLYING"; ICU_WX="ICAO_WX"; ETOPS="ETOPS"


@dataclass
class CrewMember:
    crew_id: str; base_hub: str; qualifications: set[Qualification]
    duty_clock_start: Optional[datetime]=None; current_location: str=""
    last_rest_end: Optional[datetime]=None


@dataclass
class FlightLeg:
    flight_id: str; origin: str; destination: str
    scheduled_dep: datetime; scheduled_arr: datetime; aircraft_type: str
    is_deadhead: bool=False


@dataclass
class Assignment:
    crew_id: str; flight_legs: list[FlightLeg]
    duty_start: datetime; duty_end: datetime


class RulesEngine:
    """Pure, independently testable DGCA-oriented legality checks."""

    RULESET_VERSION="dgca-car-sec7-serj-ptiii-2024.1"
    RULE_REFERENCE="DGCA-CAR-SEC7-SERJ-PTIII"
    MAX_FLIGHT_HOURS=9
    MIN_REST_HOURS=10
    MAX_DEADHEAD_HOURS=8
    MIN_CONNECTION_MINUTES=30
    MAX_CONSECUTIVE_DAYS=6

    # Conservative unaugmented FDP profile by sectors. The approved airline
    # scheme remains authoritative in production.
    FDP_BY_SECTORS={1:14.0,2:14.0,3:13.5,4:13.0,5:12.5}

    @staticmethod
    def _violation(code,message,rule_ref,entity_id=None,**details):
        return RuleViolation(code,message,rule_ref,entity_id=entity_id,details=details)

    @classmethod
    def max_fdp(cls,assignment):
        sectors=max(1,len([x for x in assignment.flight_legs if not x.is_deadhead]))
        limit=cls.FDP_BY_SECTORS.get(min(sectors,5),11.0)
        # Conservative WOCL protection for a duty starting 0200-0559 local.
        if 2 <= assignment.duty_start.hour < 6: limit-=1.0
        return limit

    @classmethod
    def validate_assignment(cls,crew,assignment):
        checks=(cls._check_duty_time,cls._check_flight_time,
                lambda a: cls._check_rest_period(crew,a),
                lambda a: cls._check_qualifications(crew,a),
                cls._check_deadhead_limits,cls._check_no_deadhead_loops,
                lambda a: cls._check_temporal_and_geographic_continuity(crew,a))
        violations=[]
        for check in checks: violations.extend(check(assignment))
        return violations

    @classmethod
    def _check_duty_time(cls,a):
        actual=(a.duty_end-a.duty_start).total_seconds()/3600; limit=cls.max_fdp(a)
        return [] if actual<=limit else [cls._violation("FDP_LIMIT",f"Duty time {actual:.1f}h exceeds {limit:.1f}h limit",f"{cls.RULE_REFERENCE}-FDP",a.crew_id,actual_hours=actual,limit_hours=limit)]

    @classmethod
    def _check_flight_time(cls,a):
        actual=sum((x.scheduled_arr-x.scheduled_dep).total_seconds()/3600 for x in a.flight_legs if not x.is_deadhead)
        return [] if actual<=cls.MAX_FLIGHT_HOURS else [cls._violation("FLIGHT_TIME_LIMIT",f"Flight time {actual:.1f}h exceeds {cls.MAX_FLIGHT_HOURS}h",f"{cls.RULE_REFERENCE}-FTL",a.crew_id,actual_hours=actual)]

    @classmethod
    def _check_rest_period(cls,crew,a):
        if crew.last_rest_end is None:return []
        actual=(a.duty_start-crew.last_rest_end).total_seconds()/3600
        return [] if actual>=cls.MIN_REST_HOURS else [cls._violation("MIN_REST",f"Rest period {actual:.1f}h below {cls.MIN_REST_HOURS}h minimum",f"{cls.RULE_REFERENCE}-REST",crew.crew_id,actual_hours=actual)]

    @classmethod
    def _check_qualifications(cls,crew,a):
        out=[]
        for leg in a.flight_legs:
            if leg.is_deadhead:continue
            name=leg.aircraft_type.replace("neo","")
            try:required=Qualification[name]
            except KeyError:
                out.append(cls._violation("UNKNOWN_AIRCRAFT",f"Unknown aircraft type {leg.aircraft_type}","OPERATOR-AOM",leg.flight_id));continue
            if required not in crew.qualifications:out.append(cls._violation("MISSING_QUALIFICATION",f"Missing qualification {required.value}",f"{cls.RULE_REFERENCE}-QUAL",leg.flight_id,required=required.value))
        return out

    @classmethod
    def _check_deadhead_limits(cls,a):
        actual=sum((x.scheduled_arr-x.scheduled_dep).total_seconds()/3600 for x in a.flight_legs if x.is_deadhead)
        return [] if actual<=cls.MAX_DEADHEAD_HOURS else [cls._violation("DEADHEAD_LIMIT",f"Deadhead time {actual:.1f}h exceeds {cls.MAX_DEADHEAD_HOURS}h","OPERATOR-DEADHEAD",a.crew_id)]

    @classmethod
    def _check_no_deadhead_loops(cls,a):
        locations=[]
        for leg in a.flight_legs:
            if leg.is_deadhead:locations.extend((leg.origin,leg.destination))
        seen=set()
        for loc in locations:
            if loc in seen:return [cls._violation("DEADHEAD_LOOP",f"Deadhead loop detected at {loc}","SKYSOLVER-SAFETY-001",a.crew_id)]
            seen.add(loc)
        return []

    @classmethod
    def _check_temporal_and_geographic_continuity(cls,crew,a):
        out=[]; legs=sorted(a.flight_legs,key=lambda x:x.scheduled_dep)
        for leg in legs:
            if leg.scheduled_arr<=leg.scheduled_dep:out.append(cls._violation("INVALID_LEG_TIME",f"{leg.flight_id} arrives before departure","DATA-QUALITY",leg.flight_id))
        if legs and crew.current_location and legs[0].origin!=crew.current_location:out.append(cls._violation("CREW_POSITION",f"Crew is at {crew.current_location}, not {legs[0].origin}","OPERATIONAL-CONTINUITY",crew.crew_id))
        for previous,current in zip(legs,legs[1:]):
            if previous.destination!=current.origin:out.append(cls._violation("LOCATION_DISCONTINUITY",f"Sequence jumps from {previous.destination} to {current.origin}","OPERATIONAL-CONTINUITY",current.flight_id))
            minutes=(current.scheduled_dep-previous.scheduled_arr).total_seconds()/60
            if minutes<cls.MIN_CONNECTION_MINUTES:out.append(cls._violation("CONNECTION_TIME",f"Connection is {minutes:.0f}m; minimum {cls.MIN_CONNECTION_MINUTES}m","OPERATOR-CONNECTION",current.flight_id))
        return out

    @classmethod
    def can_assign(cls,crew,assignment):return not cls.validate_assignment(crew,assignment)
    @classmethod
    def max_extended_duty(cls,assignment):return cls.max_fdp(assignment)


def validate(crew,assignment):return RulesEngine.validate_assignment(crew,assignment)
