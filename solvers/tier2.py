"""Tier 2 optimization upgrade.

Legal assignment columns are generated through the dedicated rules layer and
selected by an actual binary set-partitioning MILP when a configured solver is
available. This is restricted-master optimization, not branch-and-price or a
claim of global optimality. If no solver is available, Tier 1 remains the
incumbent and the result says so explicitly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Dict, Set, Optional, Tuple, Iterator, Any
import os
from datetime import datetime, timedelta

from rules.engine import (
    CrewMember,
    FlightLeg,
    Assignment,
    Qualification,
    validate,
    RulesEngine,
)


# ----------------------------------------------------------------------
# COLUMN GENERATION OPTIMIZER
# ----------------------------------------------------------------------

@dataclass
class Column:
    """A potential crew assignment (sequence of flight legs)."""
    crew_id: str
    legs: Tuple[FlightLeg, ...]
    cost: float
    violations: List[str] = tuple()  # Empty = legal


@dataclass
class OptimizationMetadata:
    status: str
    solver_name: str | None
    objective_value: float | None
    best_bound: float | None
    optimality_gap: float | None
    elapsed_s: float
    generated_columns: int
    incumbent_coverage: float
    result_coverage: float
    upgraded: bool
    message: str


@dataclass
class OptimizationResult:
    assignments: List[Assignment]
    uncovered: List[FlightLeg]
    metadata: OptimizationMetadata

    @property
    def converged(self) -> bool:
        return not self.uncovered and self.metadata.status in {"optimal", "feasible", "timeboxed_feasible"}


class ColumnGenerationSolver:
    """
    Legal-column generator retained for the restricted MILP master.

    Each column represents a potential crew assignment. The master problem
    selects columns to cover all flights. Subproblem generates new columns.
    """

    def __init__(self, time_budget_s: float = 300.0):
        self.time_budget_s = time_budget_s
        self.columns: Dict[Tuple[str, int], Column] = {}  # (crew_id, hash(legs)) -> Column
        self.selected_columns: Set[Tuple[str, int]] = set()

    def _compute_duty_cost(self, legs: List[FlightLeg]) -> float:
        """Compute duty time cost for a leg sequence."""
        if not legs:
            return 0.0
        min_start = min(leg.scheduled_dep for leg in legs)
        max_end = max(leg.scheduled_arr for leg in legs)
        duty_hours = (max_end - min_start).total_seconds() / 3600.0
        deadhead_hours = sum(
            (leg.scheduled_arr - leg.scheduled_dep).total_seconds() / 3600.0
            for leg in legs if leg.is_deadhead
        )
        return duty_hours + 0.5 * deadhead_hours

    def _generate_columns_for_crew(
        self,
        crew: CrewMember,
        flights: List[FlightLeg],
        deadline: float
    ) -> List[Column]:
        """
        Generate legal columns for a crew using greedy path extension.
        Lightweight version suitable for time-boxed operation.
        """
        if time.monotonic() > deadline:
            return []

        eligible_flights = [
            f for f in flights
            if f.origin == crew.current_location or f.origin == crew.base_hub
        ]

        columns: List[Column] = []

        # Generate single-leg columns
        for leg in eligible_flights:
            if time.monotonic() > deadline:
                break
            candidate = Assignment(
                crew_id=crew.crew_id,
                flight_legs=[leg],
                duty_start=leg.scheduled_dep,
                duty_end=leg.scheduled_arr,
            )
            violations = validate(crew, candidate)
            if not violations:
                columns.append(Column(
                    crew_id=crew.crew_id,
                    legs=(leg,),
                    cost=self._compute_duty_cost([leg]),
                ))

        # Extend to multi-leg columns (up to 4 legs to keep it bounded)
        for _ in range(3):  # Extend up to 3 levels deep
            if time.monotonic() > deadline:
                break
            extended = self._extend_columns(columns, crew, flights, deadline)
            if not extended:
                break
            columns.extend(extended)

        return columns

    def _extend_columns(
        self,
        existing: List[Column],
        crew: CrewMember,
        flights: List[FlightLeg],
        deadline: float
    ) -> List[Column]:
        """Extend existing columns by adding one more leg."""
        extended: List[Column] = []

        for col in existing:
            if time.monotonic() > deadline:
                break

            # Find flights that start where the last flight ends
            last_dest = col.legs[-1].destination
            used = {leg.flight_id for leg in col.legs}
            for flight in flights:
                if time.monotonic() > deadline:
                    break
                if flight.flight_id in used or flight.origin != last_dest:
                    continue
                if flight.scheduled_dep < col.legs[-1].scheduled_arr + timedelta(minutes=RulesEngine.MIN_CONNECTION_MINUTES):
                    continue
                legs = list(col.legs) + [flight]
                candidate = Assignment(crew.crew_id, legs, legs[0].scheduled_dep, legs[-1].scheduled_arr)
                if not validate(crew, candidate):
                    extended.append(Column(crew.crew_id, tuple(legs), self._compute_duty_cost(legs)))

        return extended

    def _master_problem_solve(
        self,
        crew_pool: List[CrewMember],
        flights: List[FlightLeg],
        columns: List[Column]
    ) -> Optional[Dict[str, List[Column]]]:
        """
        Legacy development selector. Production Tier 2 uses
        :class:`RestrictedMasterOptimizer` below.
        Returns dict mapping flight_id -> selected column, or None if inconverge.
        """
        # Build coverage map
        flight_to_columns: Dict[str, List[Column]] = {f.flight_id: [] for f in flights}
        for col in columns:
            for leg in col.legs:
                if leg.flight_id in flight_to_columns:
                    flight_to_columns[leg.flight_id].append(col)

        # Greedy selection: pick best column for each uncovered flight.
        # Each crew may cover at most one flight (set partitioning) so every
        # emitted assignment is a single, independently-validated column -> legal.
        selected: Dict[str, List[Column]] = {}
        covered_flights: Set[str] = set()
        used_crews: Set[str] = set()

        # Sort flights by earliest departure (most urgent first)
        sorted_flights = sorted(flights, key=lambda f: f.scheduled_dep)

        for flight in sorted_flights:
            if flight.flight_id in covered_flights:
                continue

            # Find best column that covers this flight, is legal, and uses a
            # crew not already assigned to another flight.
            best_col: Optional[Column] = None
            for col in flight_to_columns.get(flight.flight_id, []):
                if any(l.flight_id in covered_flights for l in col.legs):
                    continue  # Skip if overlaps with already covered flights
                if col.crew_id in used_crews:
                    continue  # One crew per flight (set partitioning)
                if best_col is None or col.cost < best_col.cost:
                    best_col = col

            if best_col:
                for leg in best_col.legs:
                    covered_flights.add(leg.flight_id)
                used_crews.add(best_col.crew_id)
                if flight.flight_id not in selected:
                    selected[flight.flight_id] = []
                selected[flight.flight_id].append(best_col)

        return selected

    def solve(
        self,
        crew_pool: List[CrewMember],
        flights: List[FlightLeg],
        initial_assignments: Optional[List[Assignment]] = None
    ) -> List[Assignment]:
        """
        Run column generation algorithm.

        Returns assignments. If time expires, returns best partial solution.
        """
        deadline = time.monotonic() + self.time_budget_s
        all_columns: List[Column] = []

        # Warm start: use Tier 1 initial assignments as starting columns
        if initial_assignments:
            for a in initial_assignments:
                crew = next((c for c in crew_pool if c.crew_id == a.crew_id), None)
                if crew:
                    all_columns.append(Column(
                        crew_id=a.crew_id,
                        legs=tuple(a.flight_legs),
                        cost=self._compute_duty_cost(a.flight_legs),
                    ))

        # Generate columns for each crew
        for crew in crew_pool:
            if time.monotonic() > deadline:
                break
            cols = self._generate_columns_for_crew(crew, flights, deadline)
            all_columns.extend(cols)

        # Solve master problem
        result = self._master_problem_solve(crew_pool, flights, all_columns)

        if result is None:
            # Return initial assignments if we have them, otherwise empty list
            if initial_assignments:
                return initial_assignments
            return []

        # Convert selected columns back to Assignments.
        # Group all selected columns by crew so a crew selected for multiple
        # flights gets ONE assignment containing every leg (never dropped).
        by_crew: Dict[str, List] = {}
        for cols in result.values():
            for col in cols:
                by_crew.setdefault(col.crew_id, []).append(col)

        assignments: List[Assignment] = []
        for crew_id, cols in by_crew.items():
            all_legs = [leg for col in cols for leg in col.legs]
            # Sort legs chronologically for a coherent duty window
            all_legs.sort(key=lambda f: f.scheduled_dep)
            assignments.append(Assignment(
                crew_id=crew_id,
                flight_legs=all_legs,
                duty_start=min(leg.scheduled_dep for leg in all_legs),
                duty_end=max(leg.scheduled_arr for leg in all_legs),
            ))

        return assignments


class RestrictedMasterOptimizer:
    """Binary set-partitioning master over independently legal columns."""

    def __init__(self, time_budget_s: float = 300.0, solver_name: str | None = None):
        self.time_budget_s = time_budget_s
        self.solver_name = solver_name or os.environ.get("SKYSOLVER_MILP_SOLVER", "highs")

    @staticmethod
    def build_model(columns: List[Column], flights: List[FlightLeg]):
        from pyomo.environ import Binary, ConcreteModel, Constraint, Objective, RangeSet, Set, Var, minimize

        model = ConcreteModel()
        model.C = RangeSet(0, max(len(columns) - 1, 0)) if columns else Set(initialize=[])
        model.F = Set(initialize=[flight.flight_id for flight in flights], ordered=True)
        model.x = Var(model.C, domain=Binary)
        model.uncovered = Var(model.F, domain=Binary)
        coverage = {flight.flight_id: [index for index, column in enumerate(columns)
                                      if any(leg.flight_id == flight.flight_id for leg in column.legs)]
                    for flight in flights}
        crew_columns: Dict[str, List[int]] = {}
        for index, column in enumerate(columns):
            crew_columns.setdefault(column.crew_id, []).append(index)

        def cover_rule(instance, flight_id):
            return sum(instance.x[index] for index in coverage[flight_id]) + instance.uncovered[flight_id] == 1

        model.cover_exactly_once = Constraint(model.F, rule=cover_rule)
        model.CREW = Set(initialize=sorted(crew_columns))
        model.one_duty_per_crew = Constraint(
            model.CREW,
            rule=lambda instance, crew_id: sum(instance.x[index] for index in crew_columns[crew_id]) <= 1,
        )
        model.objective = Objective(
            expr=10_000 * sum(model.uncovered[flight_id] for flight_id in model.F)
                 + sum(columns[index].cost * model.x[index] for index in model.C),
            sense=minimize,
        )
        return model

    def solve(self, crew_pool: List[CrewMember], flights: List[FlightLeg],
              tier1_initial: Optional[List[Assignment]] = None) -> OptimizationResult:
        started = time.monotonic()
        incumbent = list(tier1_initial or [])
        incumbent_covered = {leg.flight_id for assignment in incumbent for leg in assignment.flight_legs}
        generator = ColumnGenerationSolver(max(0.01, self.time_budget_s * 0.35))
        deadline = time.monotonic() + max(0.01, self.time_budget_s * 0.35)
        columns: List[Column] = []
        for assignment in incumbent:
            columns.append(Column(assignment.crew_id, tuple(assignment.flight_legs), generator._compute_duty_cost(assignment.flight_legs)))
        for crew in crew_pool:
            if time.monotonic() >= deadline:
                break
            columns.extend(generator._generate_columns_for_crew(crew, flights, deadline))
        unique: Dict[tuple[str, tuple[str, ...]], Column] = {}
        for column in columns:
            key = (column.crew_id, tuple(leg.flight_id for leg in column.legs))
            unique[key] = column
        columns = list(unique.values())
        base_coverage = len(incumbent_covered) / max(len(flights), 1)
        try:
            from pyomo.environ import SolverFactory, value
            model = self.build_model(columns, flights)
            solver = SolverFactory(self.solver_name)
            if not solver.available(exception_flag=False):
                raise RuntimeError(f"Configured MILP solver '{self.solver_name}' is unavailable")
            for index, column in enumerate(columns):
                if any(column.crew_id == item.crew_id and
                       {leg.flight_id for leg in column.legs} == {leg.flight_id for leg in item.flight_legs}
                       for item in incumbent):
                    model.x[index].value = 1
            if self.solver_name in {"highs", "appsi_highs"}:
                solver.options["time_limit"] = max(0.01, self.time_budget_s - (time.monotonic() - started))
            result = solver.solve(model, tee=False, load_solutions=False)
            termination = str(result.solver.termination_condition).lower()
            try:
                model.solutions.load_from(result)
            except Exception:
                # Cold-start / no loadable solution within the budget: retain the legal
                # Tier 1 incumbent cleanly instead of surfacing a raw solver error.
                uncovered = [flight for flight in flights if flight.flight_id not in incumbent_covered]
                return OptimizationResult(incumbent, uncovered, OptimizationMetadata(
                    "timeboxed_feasible", self.solver_name, None, None, None,
                    time.monotonic()-started, len(columns), base_coverage, base_coverage, False,
                    "MILP produced no loadable solution within the time budget; Tier 1 legal incumbent retained"))
            selected = [columns[index] for index in range(len(columns)) if value(model.x[index]) >= 0.5]
            assignments = [Assignment(column.crew_id, list(column.legs),
                                      min(leg.scheduled_dep for leg in column.legs),
                                      max(leg.scheduled_arr for leg in column.legs)) for column in selected]
            covered = {leg.flight_id for assignment in assignments for leg in assignment.flight_legs}
            uncovered = [flight for flight in flights if flight.flight_id not in covered]
            coverage = len(covered) / max(len(flights), 1)
            if coverage < base_coverage:
                assignments = incumbent
                covered = incumbent_covered
                uncovered = [flight for flight in flights if flight.flight_id not in covered]
                coverage = base_coverage
                upgraded = False
                message = "MILP result was worse than the legal Tier 1 incumbent and was rejected"
            else:
                upgraded = coverage > base_coverage or value(model.objective) < 10_000 * (len(flights)-len(incumbent_covered))
                message = "Restricted MILP master returned a legal incumbent upgrade" if upgraded else "MILP retained Tier 1 incumbent"
            status = "optimal" if "optimal" in termination else ("timeboxed_feasible" if "time" in termination else "feasible")
            return OptimizationResult(assignments, uncovered, OptimizationMetadata(
                status, self.solver_name, float(value(model.objective)), None, None,
                time.monotonic()-started, len(columns), base_coverage, coverage, upgraded, message,
            ))
        except Exception as exc:
            uncovered = [flight for flight in flights if flight.flight_id not in incumbent_covered]
            return OptimizationResult(incumbent, uncovered, OptimizationMetadata(
                "solver_unavailable", self.solver_name, None, None, None,
                time.monotonic()-started, len(columns), base_coverage, base_coverage, False, str(exc),
            ))


# ----------------------------------------------------------------------
# TIER 2 API
# ----------------------------------------------------------------------

def solve_partition(
    crew_pool: List[CrewMember],
    flights: List[FlightLeg],
    time_budget_s: float = 300.0,
    tier1_initial: Optional[List[Assignment]] = None
) -> Tuple[List[Assignment], List[FlightLeg], float, bool]:
    """
    Tier 2 MILP-based solver for a regional partition.

    Returns: (assignments, uncovered_flights, elapsed_s, converged)
    - converged=True if all flights covered within time budget
    - converged=False if time expired, returned partial solution
    """
    result = solve_partition_detailed(crew_pool, flights, time_budget_s, tier1_initial)
    return result.assignments, result.uncovered, result.metadata.elapsed_s, result.converged


def solve_partition_detailed(
    crew_pool: List[CrewMember], flights: List[FlightLeg], time_budget_s: float = 300.0,
    tier1_initial: Optional[List[Assignment]] = None,
) -> OptimizationResult:
    return RestrictedMasterOptimizer(time_budget_s).solve(crew_pool, flights, tier1_initial)
