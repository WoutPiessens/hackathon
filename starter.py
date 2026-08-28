"""ACP Summer School 2026 — Python starter.

The wrapper below reads an instance JSON, calls solve(), and writes a
solution JSON in the format the leaderboard expects. You should only need
to edit the body of solve() — the I/O plumbing is done for you.

Usage
-----
    # solve one instance
    python3 starter.py data/hackathon_02.json

    # solve every instance in a folder (writes sol_XX.json next to each)
    python3 starter.py data/

    # write the solution somewhere specific
    python3 starter.py data/hackathon_02.json -o my_solution.json

Submit the resulting sol_*.json (or your own filename ending in _XX.json)
on the leaderboard site.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# =============================================================================
#  YOUR CODE — everything above and below this block is I/O plumbing.
# =============================================================================
import cpmpy as cp


def solve(
    instance: dict,
    disabled_constraints: set[str] | None = None,
    show_progress: bool = True,
    timing: dict[str, object] | None = None,
    time_limit: float | None = None,
    solver_options: dict[str, object] | None = None,
) -> dict:
    """Build a solution for one instance.

    ``instance`` is a dict loaded from an hackathon_XX.json file. It uses a FLAT
    schema: every per-flight / per-gate / per-team field is a top-level array
    indexed positionally by FlightID / GateID / LaborID. Keys:

    We have provided a trivial placeholder implementation that parks every flight at
    the first gate and staffs every task with the first team. It is only shape-valid.
    Please replace the followi  ng with your own solver.
    """
    disabled_constraints = {name.upper() for name in (disabled_constraints or set())}

    def enabled(name: str) -> bool:
        return name.upper() not in disabled_constraints

    build_started = time.perf_counter()

    # ---- REPLACE FROM HERE ------------------------------------------------
    # Trivial placeholder: parks every flight at the first gate and staffs each
    # task with the first team. It is only shape-valid.
    F = len(instance["FlightID"])
    G = len(instance["GateID"])
    model = cp.Model()

    gate_used = cp.intvar(shape=F, lb=0, ub=G - 1, name="gate_used")

    # C1
    if enabled("C1"):
        for f in range(F):
            for g in range(G):
                if (
                    instance["flight_arr"][f] < instance["gate_open"][g]
                    or instance["flight_dep"][f] > instance["gate_close"][g]
                ):
                    model += gate_used[f] != g

    # C2
    if enabled("C2"):
        for f in range(F):
            for g in range(G):
                if (
                    instance["flight_size"][f] == "wide"
                    and instance["gate_stand_size"][g] == "small"
                ):
                    model += gate_used[f] != g

    # C3

    if enabled("C3"):
        for f in range(F):
            for g in range(G):
                if (
                    instance["flight_op_type"][f]
                    != instance["gate_op_type"][g]
                    == "wide"
                ):
                    model += gate_used[f] != g

    # C4

    if enabled("C4"):
        for f in range(F):
            for g in range(G):
                if instance["flight_carrier"][f] != instance["gate_usage"][g] == "wide":
                    model += gate_used[f] != g

    # C5

    if enabled("C5"):
        for g in range(G):
            # existing_flights = [f for f in range(F) if gate_used[f] == g]
            # model += cp.NoOverlapOptional([1,1], [2,2], [3,3], [True, False])
            model += cp.NoOverlapOptional(
                start=[instance["flight_arr"][f] for f in range(F)],
                duration=[
                    instance["flight_dep"][f] - instance["flight_arr"][f] + 30
                    for f in range(F)
                ],
                end=[instance["flight_dep"][f] + 30 for f in range(F)],
                is_present=[gate_used[f] == g for f in range(F)],
            )

    # define map for which team kind can do which type of task
    task_to_team_type_map = {
        "ARRIVE_SECURE": "ramp_team",
        "DISEMBARK": "ramp_team",
        "INTL_DOCS": "ramp_team",
        "BOARDING": "ramp_team",
        "BAG_UNLOAD": "baggage_team",
        "BAG_LOAD": "baggage_team",
        "CARGO_UNLOAD": "baggage_team",
        "CARGO_LOAD": "baggage_team",
        "FUEL": "fuel_team",
        "CATERING": "catering_team",
        "CABIN_CLEAN": "cabin_clean_team",
        "WATER_LAV": "water_waste_team",
        "PUSHBACK": "pushback_team",
        "DEP_RELEASE": "pushback_team",
    }

    # C8: task precedence graphs, read off Figures 1-3 of hackathon.pdf.
    # One dict per service profile; each maps a task kind -> the set of task
    # kinds that must FINISH before it starts. A flight's profile is the
    # combination of its carrier and operation type.

    # Figure 1: domestic passenger profile.
    preds_domestic_passenger = {
        "ARRIVE_SECURE": set(),
        "DISEMBARK": {"ARRIVE_SECURE"},
        "BAG_UNLOAD": {"ARRIVE_SECURE"},
        "FUEL": {"DISEMBARK"},
        "CABIN_CLEAN": {"DISEMBARK"},
        "WATER_LAV": {"DISEMBARK"},
        "CATERING": {"DISEMBARK"},
        "BAG_LOAD": {"BAG_UNLOAD"},
        "BOARDING": {"FUEL", "CABIN_CLEAN", "WATER_LAV", "CATERING"},
        "PUSHBACK": {"BOARDING", "BAG_LOAD"},
    }

    # Figure 2: international passenger profile. Same shape as Figure 1, but the
    # four service tasks feed INTL_DOCS, which is BOARDING's only predecessor.
    preds_international_passenger = {
        "ARRIVE_SECURE": set(),
        "DISEMBARK": {"ARRIVE_SECURE"},
        "BAG_UNLOAD": {"ARRIVE_SECURE"},
        "FUEL": {"DISEMBARK"},
        "CABIN_CLEAN": {"DISEMBARK"},
        "WATER_LAV": {"DISEMBARK"},
        "CATERING": {"DISEMBARK"},
        "BAG_LOAD": {"BAG_UNLOAD"},
        "INTL_DOCS": {"FUEL", "CABIN_CLEAN", "WATER_LAV", "CATERING"},
        "BOARDING": {"INTL_DOCS"},
        "PUSHBACK": {"BOARDING", "BAG_LOAD"},
    }

    # Figure 3: freighter profile (both domestic and international).
    preds_freighter = {
        "CARGO_UNLOAD": set(),
        "CARGO_LOAD": {"CARGO_UNLOAD"},
        "FUEL": {"CARGO_UNLOAD"},
        "DEP_RELEASE": {"CARGO_LOAD", "FUEL"},
    }

    def preds_for_flight(f: int) -> dict[str, set[str]]:
        """Pick the precedence graph matching flight f's service profile."""
        if instance["flight_op_type"][f] == "freighter":
            return preds_freighter
        if instance["flight_carrier"][f] == "international":
            return preds_international_passenger
        return preds_domestic_passenger

    d1_task_starts = cp.intvar(shape=sum(instance["flight_n_tasks"]), lb=0, ub=24 * 60)
    tasks_to_team = cp.intvar(
        shape=sum(instance["flight_n_tasks"]),
        lb=0,
        ub=len(instance["LaborID"]) - 1,  # TODO really big domain
    )
    flattened_tasks = [
        task
        for tasks, task_count in zip(
            instance["flight_tasks"], instance["flight_n_tasks"], strict=True
        )
        for task in tasks[:task_count]
    ]
    task_to_flight = [
        flight_index
        for flight_index, task_count in enumerate(instance["flight_n_tasks"])
        for _ in range(task_count)
    ]

    task_duration = [task["duration"] for task in flattened_tasks]

    task_required_team_kind = [
        task_to_team_type_map[task["kind"]] for task in flattened_tasks
    ]

    task_to_gate = [gate_used[flight_index] for flight_index in task_to_flight]
    # Task <-> Team mappings
    team_to_possible_tasks = [
        [
            task_index
            for task_index, task in enumerate(flattened_tasks)
            if task_to_team_type_map[task["kind"]] == instance["labor_kind"][team_index]
        ]
        for team_index in range(len(instance["LaborID"]))
    ]
    task_to_possible_teams = [
        [
            i
            for i, team in enumerate(instance["labor_kind"])
            if task_to_team_type_map[task["kind"]] == team
        ]
        for task in flattened_tasks
    ]
    travel_intervals = {}
    # for each of the flights
    for flight_index, f in enumerate(range(F)):

        required_tasks = instance["flight_tasks"][f][: instance["flight_n_tasks"][f]]
        flight_n_tasks_start = sum(instance["flight_n_tasks"][:flight_index])
        flight_n_tasks_end = flight_n_tasks_start + instance["flight_n_tasks"][f]
        # C7: every active task stays inside its flight window.
        if enabled("C7"):
            for t in range(flight_n_tasks_start, flight_n_tasks_end):
                model += (d1_task_starts[t] >= instance["flight_arr"][f]) & (
                    d1_task_starts[t] + flattened_tasks[t]["duration"]
                    <= instance["flight_dep"][f]
                )

        if instance["flight_op_type"][f] == "passenger":
            if instance["flight_carrier"][f] == "domestic":
                flight_precedence_graph = preds_domestic_passenger
            else:
                flight_precedence_graph = preds_international_passenger
        else:
            flight_precedence_graph = preds_freighter

        # C8: precedence within a flight.
        if enabled("C8"):
            for k in flight_precedence_graph:
                for v in flight_precedence_graph[k]:
                    task_index_k = next(
                        i for i, task in enumerate(required_tasks) if task["kind"] == k
                    )
                    task_index_v = next(
                        i for i, task in enumerate(required_tasks) if task["kind"] == v
                    )
                    model += (
                        d1_task_starts[flight_n_tasks_start + task_index_k]
                        >= d1_task_starts[flight_n_tasks_start + task_index_v]
                        + flattened_tasks[flight_n_tasks_start + task_index_v][
                            "duration"
                        ]
                    )

        flight_tasks_to_team = tasks_to_team[flight_n_tasks_start:flight_n_tasks_end]

        # task_start_times = cp.intvar(
        #     shape=len(required_tasks),
        #     lb=instance["flight_arr"][f],
        #     ub=instance["flight_dep"][f],
        # )

        # Get the specific precedence graph for this flight
        # for each task
        # 1. get the task kind for the task
        # 1.5. enforce that the task kind is valid for the team kind (using the bitmap)

        # 2. retrieve from the graph the predecessors of that task kind
        # 3. enforce predecessor task must be of task kind that we just retrieved

        # C6: task/team kind compatibility.
        if enabled("C6"):
            for task_index, task in enumerate(required_tasks):
                possible_teams = [
                    i
                    for i, team in enumerate(instance["labor_kind"])
                    if task_to_team_type_map[task["kind"]] == team
                ]
                team_index_start_that_can_do_kind = possible_teams[0]
                team_index_end_that_can_do_kind = possible_teams[-1]
                # only the right team can do the task
                model += (
                    team_index_start_that_can_do_kind
                    <= flight_tasks_to_team[task_index]
                ) & (
                    flight_tasks_to_team[task_index] <= team_index_end_that_can_do_kind
                )

            # index of
    # Travel time and task-chain constraints
    if enabled("C11"):
        # Use one edge variable per task pair rather than one per
        # (team, task pair). The selected edge itself says which team owns
        # both tasks, so this is equivalent but much smaller.
        precedes = {}
        first_task = {}
        last_task = {}

        for task in range(len(flattened_tasks)):
            first_task[task] = cp.boolvar(name=f"first_{task}")
            last_task[task] = cp.boolvar(name=f"last_{task}")

        for predecessor in range(len(flattened_tasks)):
            for successor in range(len(flattened_tasks)):
                if predecessor == successor:
                    continue

                # With C6 active, tasks of different required team kinds can
                # never share a team, so those edges are unnecessary.
                if enabled("C6") and not set(
                    task_to_possible_teams[predecessor]
                ).intersection(task_to_possible_teams[successor]):
                    continue

                precedes[predecessor, successor] = cp.boolvar(
                    name=f"precedes_{predecessor}_{successor}"
                )

        # An active precedence edge means:
        # 1. both tasks are assigned to the same team;
        # 2. predecessor finishes, then travel occurs, then successor starts.
        for (predecessor, successor), edge in precedes.items():
            # Both tasks must be assigned to the same team.
            model += edge.implies(
                tasks_to_team[predecessor] == tasks_to_team[successor]
            )

            # task_to_gate contains CP variables, so use NDElement rather
            # than indexing instance["travel"] directly.
            travel_time = cp.NDElement(
                instance["travel"],
                [
                    task_to_gate[predecessor],
                    task_to_gate[successor],
                ],
            )

            # Model travel as an optional activity on this team's timeline.
            # It starts when the predecessor task finishes and is present
            # exactly when this precedence edge is selected.
            travel_start = (
                d1_task_starts[predecessor] + task_duration[predecessor]
            )
            travel_end = travel_start + travel_time
            travel_intervals[predecessor, successor] = (
                travel_start,
                travel_time,
                travel_end,
                edge,
            )

            # If the edge is active, enforce the timing constraint: predecessor finishes, then travel occurs, then successor starts.
            model += edge.implies(
                travel_end <= d1_task_starts[successor]
            )

        # Every task belongs to exactly one chain: it has exactly one incoming
        # edge unless it is first, and exactly one outgoing edge unless it is
        # last.
        for task in range(len(flattened_tasks)):
            incoming = [
                precedes[predecessor, task]
                for predecessor in range(len(flattened_tasks))
                if (predecessor, task) in precedes
            ]
            outgoing = [
                precedes[task, successor]
                for successor in range(len(flattened_tasks))
                if (task, successor) in precedes
            ]

            model += (cp.sum(incoming) if incoming else 0) + first_task[task] == 1
            model += (cp.sum(outgoing) if outgoing else 0) + last_task[task] == 1

        # Since each selected edge connects tasks assigned to the same team,
        # require exactly one first and one last task for every used team.
        for team_index in range(len(instance["LaborID"])):
            used = cp.any(tasks_to_team == team_index)

            model += cp.sum(
                first_task[task] & (tasks_to_team[task] == team_index)
                for task in range(len(flattened_tasks))
            ) == used

            model += cp.sum(
                last_task[task] & (tasks_to_team[task] == team_index)
                for task in range(len(flattened_tasks))
            ) == used

    # C9: each individual team can work on at most one task at a time.
    if enabled("C9"):
        for team_index, _ in enumerate(instance["LaborID"]):
            possible_task_ids = [
                task_id
                for task_id in range(len(flattened_tasks))
                if not enabled("C6") or team_index in task_to_possible_teams[task_id]
            ]

            starts = [d1_task_starts[t] for t in possible_task_ids]
            durations = [task_duration[t] for t in possible_task_ids]
            ends = [d1_task_starts[t] + task_duration[t] for t in possible_task_ids]
            present = [tasks_to_team[t] == team_index for t in possible_task_ids]

            # Do not add every possible travel interval here: that would make
            # NoOverlapOptional compare O(E^2) pairs of optional edges. Once
            # C11 selects one chain, its travel inequalities already order the
            # selected travel intervals between the corresponding task pairs.
            model += cp.NoOverlapOptional(
                start=starts,
                duration=durations,
                end=ends,
                is_present=present,
            )

    # enforce tasks are within shift start end
    # C10: a task must fit within its assigned team's shift.
    if enabled("C10"):
        for task_id, task in enumerate(flattened_tasks):

            x = tasks_to_team[task_id]

            model += d1_task_starts[task_id] >= cp.Element(
                instance["labor_shift_start"], x
            )

            model += d1_task_starts[task_id] + task["duration"] <= cp.Element(
                instance["labor_shift_end"], x
            )

    # Breaks
    if enabled("C12"):
        pass

    gate = []
    task_start = []
    task_labor = []
    cost = []

    obj = cp.sum(
        instance["labor_cost"][t] * (cp.any(tasks_to_team == t))
        for t in range(len(instance["LaborID"]))
    )
    if enabled("OBJ"):
        model.minimize(obj)

    # ---- intermediate-solution callback -------------------------------------
    # CP-SAT hands back every improving solution it finds along the way, not
    # just the last one. Print a one-line progress record for each so a long
    # run reports what it is doing instead of sitting silent.
    # With minimise active these are improving incumbents, so cost falls
    # monotonically; on a pure satisfaction solve it would jump around instead.
    solve_started = time.perf_counter()
    n_found = [0]

    def on_solution() -> None:
        n_found[0] += 1
        print(
            f"    [sol {n_found[0]:>3}] "
            f"t={time.perf_counter() - solve_started:6.2f}s "
            f"cost={obj.value()}",
            file=sys.stderr,
            flush=True,
        )

    if timing is not None:
        timing["build_s"] = time.perf_counter() - build_started

    solve_kwargs: dict[str, object] = {"solver": "ortools"}
    if time_limit is not None:
        solve_kwargs["time_limit"] = time_limit
    if show_progress:
        solve_kwargs["display"] = on_solution
    if solver_options:
        solve_kwargs.update(solver_options)
    solved = model.solve(**solve_kwargs)
    if timing is not None:
        timing["solver_s"] = time.perf_counter() - solve_started
        timing["solver_status"] = (
            str(model.status().exitstatus).rsplit(".", 1)[-1].lower()
        )

    if solved:
        gate_values = gate_used.value()
        if gate_values is None:
            gate = [0] * F
        else:
            gate = [0 if g is None else int(g) for g in gate_values.tolist()]
        gate = [instance["GateID"][g] for g in gate]

        task_labor_values = tasks_to_team.value()
        task_start_values = d1_task_starts.value()
        task_labor_flat = (
            [0] * len(flattened_tasks)
            if task_labor_values is None
            else [
                0 if value is None else int(value)
                for value in task_labor_values.tolist()
            ]
        )
        task_start_flat = (
            [0] * len(flattened_tasks)
            if task_start_values is None
            else [
                0 if value is None else int(value)
                for value in task_start_values.tolist()
            ]
        )

        start = 0
        task_labor = []
        task_start = []

        for size in instance["flight_n_tasks"]:
            task_labor.append(task_labor_flat[start : start + size])
            task_start.append(task_start_flat[start : start + size])
            start += size

        task_labor = [
            [instance["LaborID"][l] for l in sublist] for sublist in task_labor
        ]
        cost = model.objective_value()

        # print(task_starts, tasks_to_team_1)

    """G0 = instance["GateID"][0]
    L0 = instance["LaborID"][0]



    gate = [G0] * F
    task_start = []
    task_labor = []
    for f in range(F):
        tasks = instance["flight_tasks"][f][: instance["flight_n_tasks"][f]]
        task_start.append([instance["flight_arr"][f]] * len(tasks))
        task_labor.append([L0] * len(tasks))   # one team id per task

    cost = 0"""
    for team_index in []:
        # variable on start times of tasks
        # variable on what tasks
        pass
    # ---- REPLACE UNTIL HERE -----------------------------------------------
    return {
        "gate": gate,
        "task_start": task_start,
        "task_labor": task_labor,
        "cost": cost,
    }


# =============================================================================
#  Wrapper below — you shouldn't need to touch anything past this line.
# =============================================================================

REQUIRED_KEYS = ("gate", "task_start", "task_labor", "cost")


def load_instance(path: Path) -> dict:
    return json.loads(path.read_text())


def dump_solution(solution: dict, path: Path) -> None:
    path.write_text(json.dumps(solution, indent=2))


def default_output_name(instance_path: Path, outdir: Path) -> Path:
    m = re.search(r"(\d{2})", instance_path.stem)
    stem = f"sol_{m.group(1)}" if m else "sol_" + instance_path.stem
    return outdir / f"{stem}.json"


def solve_one(instance_path: Path, out_path: Path) -> None:
    instance = load_instance(instance_path)
    print(
        f"[{instance_path.name}] "
        f"{len(instance['FlightID'])} flights, "
        f"{len(instance['GateID'])} gates, "
        f"{len(instance['LaborID'])} teams, "
        f"horizon = {instance['horizon']}",
        file=sys.stderr,
    )

    solution = solve(instance)

    missing = [k for k in REQUIRED_KEYS if k not in solution]
    if missing:
        sys.exit(f"solve() did not return required key(s): {missing}")

    print(solution)

    dump_solution(solution, out_path)
    print(
        f"[{instance_path.name}] wrote {out_path} "
        f"(claimed cost {solution['cost']})",
        file=sys.stderr,
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run solve() against one instance or every instance in a folder."
    )
    ap.add_argument(
        "path",
        type=Path,
        help="Path to an instance JSON, or a folder containing "
        "hackathon_XX.json files.",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path. When PATH is a single file this "
        "is a filename; when PATH is a folder this is a "
        "target directory. Defaults to the current dir.",
    )
    args = ap.parse_args()

    if args.path.is_dir():
        outdir = args.output or Path.cwd()
        outdir.mkdir(parents=True, exist_ok=True)
        instances = sorted(args.path.glob("hackathon_*.json"))
        if not instances:
            sys.exit(f"no hackathon_*.json found in {args.path}")
        for inst in instances:
            solve_one(inst, default_output_name(inst, outdir))
    else:
        out = args.output or default_output_name(args.path, Path.cwd())
        solve_one(args.path, out)


if __name__ == "__main__":
    main()
