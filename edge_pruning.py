"""Pure filters for candidate C11 task-precedence edges.

These functions deliberately do not import CPMPy or mutate a model. They use
only static instance data and enabled-constraint flags to remove edges that
cannot occur in any schedule satisfying the corresponding constraints.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from math import inf


def travel_lower_bounds(
    travel: Sequence[Sequence[int]],
) -> tuple[int, int | float]:
    """Return global and distinct-gate lower bounds on travel time."""
    minimum_travel = min(value for row in travel for value in row)
    distinct_gate_values = [
        travel[g1][g2]
        for g1 in range(len(travel))
        for g2 in range(len(travel))
        if g1 != g2
    ]
    minimum_different_gate_travel = (
        min(distinct_gate_values) if distinct_gate_values else inf
    )
    return minimum_travel, minimum_different_gate_travel


def can_precede(
    predecessor: int,
    successor: int,
    *,
    task_to_flight: Sequence[int],
    task_duration: Sequence[int],
    task_to_possible_teams: Sequence[Sequence[int]],
    flight_arr: Sequence[int],
    flight_dep: Sequence[int],
    labor_shift_start: Sequence[int],
    labor_shift_end: Sequence[int],
    minimum_travel: int,
    minimum_different_gate_travel: int | float,
    c5_enabled: bool,
    c6_enabled: bool,
    c7_enabled: bool,
    c10_enabled: bool,
    min_gate_gap: int = 30,
) -> bool:
    """Return whether one team could possibly perform predecessor then successor.

    Every rejection is based on a necessary condition, so this filter may keep
    some impossible edges but must not remove a feasible one.
    """
    predecessor_flight = task_to_flight[predecessor]
    successor_flight = task_to_flight[successor]

    if c6_enabled:
        candidate_teams = set(task_to_possible_teams[predecessor]).intersection(
            task_to_possible_teams[successor]
        )
    else:
        candidate_teams = range(len(labor_shift_start))

    if not candidate_teams:
        return False

    same_gate_possible = (
        predecessor_flight == successor_flight
        or not c5_enabled
        or flight_dep[predecessor_flight] + min_gate_gap
        <= flight_arr[successor_flight]
        or flight_dep[successor_flight] + min_gate_gap
        <= flight_arr[predecessor_flight]
    )
    travel_lower_bound = (
        minimum_travel
        if same_gate_possible
        else minimum_different_gate_travel
    )

    for team_index in candidate_teams:
        earliest_predecessor_start = 0
        latest_predecessor_end = inf
        latest_successor_start = inf

        if c7_enabled:
            earliest_predecessor_start = max(
                earliest_predecessor_start,
                flight_arr[predecessor_flight],
            )
            latest_predecessor_end = min(
                latest_predecessor_end,
                flight_dep[predecessor_flight],
            )
            latest_successor_start = min(
                latest_successor_start,
                flight_dep[successor_flight] - task_duration[successor],
            )

        if c10_enabled:
            earliest_predecessor_start = max(
                earliest_predecessor_start,
                labor_shift_start[team_index],
            )
            latest_predecessor_end = min(
                latest_predecessor_end,
                labor_shift_end[team_index],
            )
            latest_successor_start = min(
                latest_successor_start,
                labor_shift_end[team_index] - task_duration[successor],
            )

        # The predecessor must fit, and its earliest completion plus a safe
        # travel lower bound must reach the successor's latest start.
        if (
            earliest_predecessor_start + task_duration[predecessor]
            > latest_predecessor_end
        ):
            continue

        if (
            earliest_predecessor_start
            + task_duration[predecessor]
            + travel_lower_bound
            <= latest_successor_start
        ):
            return True

    return False


def iter_candidate_precedence_edges(
    *,
    task_to_flight: Sequence[int],
    task_duration: Sequence[int],
    task_to_possible_teams: Sequence[Sequence[int]],
    flight_arr: Sequence[int],
    flight_dep: Sequence[int],
    labor_shift_start: Sequence[int],
    labor_shift_end: Sequence[int],
    travel: Sequence[Sequence[int]],
    c5_enabled: bool,
    c6_enabled: bool,
    c7_enabled: bool,
    c10_enabled: bool,
    min_gate_gap: int = 30,
) -> Iterator[tuple[int, int]]:
    """Yield directed task pairs that survive all safe static filters."""
    minimum_travel, minimum_different_gate_travel = travel_lower_bounds(travel)
    n_tasks = len(task_duration)

    for predecessor in range(n_tasks):
        for successor in range(n_tasks):
            if predecessor == successor:
                continue

            if can_precede(
                predecessor,
                successor,
                task_to_flight=task_to_flight,
                task_duration=task_duration,
                task_to_possible_teams=task_to_possible_teams,
                flight_arr=flight_arr,
                flight_dep=flight_dep,
                labor_shift_start=labor_shift_start,
                labor_shift_end=labor_shift_end,
                minimum_travel=minimum_travel,
                minimum_different_gate_travel=minimum_different_gate_travel,
                c5_enabled=c5_enabled,
                c6_enabled=c6_enabled,
                c7_enabled=c7_enabled,
                c10_enabled=c10_enabled,
                min_gate_gap=min_gate_gap,
            ):
                yield predecessor, successor
