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
from pathlib import Path

# =============================================================================
#  YOUR CODE — everything above and below this block is I/O plumbing.
# =============================================================================
import cpmpy as cp


def solve(instance: dict) -> dict:
    """Build a solution for one instance.

    ``instance`` is a dict loaded from an hackathon_XX.json file. It uses a FLAT
    schema: every per-flight / per-gate / per-team field is a top-level array
    indexed positionally by FlightID / GateID / LaborID. Keys:

    We have provided a trivial placeholder implementation that parks every flight at
    the first gate and staffs every task with the first team. It is only shape-valid.
    Please replace the followi  ng with your own solver.
    """
    # ---- REPLACE FROM HERE ------------------------------------------------
    # Trivial placeholder: parks every flight at the first gate and staffs each
    # task with the first team. It is only shape-valid.
    F = len(instance["FlightID"])
    G = len(instance["GateID"])
    model = cp.Model()

    gate_used = cp.intvar(shape=F, lb=0, ub=G - 1, name="gate_used")

    # C1

    for f in range(F):
        for g in range(G):
            if (
                instance["flight_arr"][f] < instance["gate_open"][g]
                or instance["flight_dep"][f] > instance["gate_close"][g]
            ):

                model += gate_used[f] != g

    # C2
    for f in range(F):
        for g in range(G):
            if (
                instance["flight_size"][f] == "wide"
                and instance["gate_stand_size"][g] == "small"
            ):
                model += gate_used[f] != g

    # C3

    for f in range(F):
        for g in range(G):
            if instance["flight_op_type"][f] != instance["gate_op_type"][g] == "wide":
                model += gate_used[f] != g

    # C4

    for f in range(F):
        for g in range(G):
            if instance["flight_carrier"][f] != instance["gate_usage"][g] == "wide":
                model += gate_used[f] != g

    # C5

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

    task_starts = cp.intvar(shape=sum(instance["flight_n_tasks"]), lb=0, ub=24 * 60)

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

    tasks_to_team = cp.intvar(
        shape=sum(instance["flight_n_tasks"]),
        lb=0,
        ub=len(instance["LaborID"]) - 1,  # TODO really big domain
    )
    flattened_tasks = [b for a in instance["flight_tasks"] for b in a]
    # for each of the flights
    for flight_index, f in enumerate(range(F)):
        required_tasks = instance["flight_tasks"][f]
        flight_n_tasks_start = sum(instance["flight_n_tasks"][:flight_index])
        flight_n_tasks_end = flight_n_tasks_start + instance["flight_n_tasks"][f]

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

        for task_index, task in enumerate(required_tasks):
            task_kind = task["kind"]
            team_type_that_can_do_task = task_to_team_type_map[task_kind]
            team_indexes_that_can_do_kind = [
                i
                for i, team in enumerate(instance["labor_kind"])
                if team_type_that_can_do_task == team
            ]
            team_index_start_that_can_do_kind = team_indexes_that_can_do_kind[0]
            team_index_end_that_can_do_kind = team_indexes_that_can_do_kind[-1]
            # only the right team can do the task
            model += (
                team_index_start_that_can_do_kind <= flight_tasks_to_team[task_index]
            ) & (flight_tasks_to_team[task_index] <= team_index_end_that_can_do_kind)

            # index of

    for task_index, _ in enumerate(instance["LaborID"]):
        flattened_tasks_1 = [flattened_tasks[i] for i in range(len(task_starts))]
        flattened_task_durations = [a["duration"] for a in flattened_tasks_1]
        # enforce no overlap for those tasks
        model += cp.NoOverlapOptional(
            start=task_starts,
            duration=flattened_task_durations,
            end=[
                a + b
                for a, b in zip(
                    task_starts,
                    flattened_task_durations,
                    strict=True,
                )
            ],
            is_present=[
                (tasks_to_team[task_id] == task_index)
                for task_id, _ in enumerate(flattened_tasks_1)
            ],
        )

    # enforce tasks are within shift start end
    for task_id, task in enumerate(flattened_tasks):

        x = tasks_to_team[task_id]

        model += task_starts[task_id] >= cp.Element(instance["labor_shift_start"], x)

        model += task_starts[task_id] + task["duration"] <= cp.Element(
            instance["labor_shift_end"], x
        )

    gate = []
    task_start = []
    task_labor = []
    cost = []

    if model.solve():
        gate = gate_used.value()

        gate = gate.tolist()
        task_starts = task_starts.value().tolist()
        tasks_to_team_1 = tasks_to_team.value().tolist()
        print(task_starts, tasks_to_team_1)

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
