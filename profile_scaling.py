"""Profile model-construction and solving time as instances get larger.

Examples
--------
    # Compare the full model with C11 disabled on every available instance.
    .venv/bin/python profile_scaling.py --variants baseline,no-c11 \
        --repeats 2 --time-limit 5

    # Profile only selected instances and save machine-readable results.
    .venv/bin/python profile_scaling.py data/hackathon_01.json \
        data/hackathon_03.json data/hackathon_05.json \
        --repeats 3 --time-limit 2 --output scaling.json

Timing fields
-------------
``build_s`` is the time spent constructing the CPMPy model, measured by the
timing hook in starter.solve() immediately before model.solve().
``solver_s`` is the time inside model.solve(), including CPMPy-to-ORTools
translation, presolve, and search. ``total_s`` is the outer wall-clock time.
Pass ``--build-only`` to construct the model without invoking the solver; this
is useful for larger instances whose search time would otherwise hide the
construction trend.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import statistics
import time
from collections import Counter
from pathlib import Path

import starter


TASK_TO_TEAM_KIND = {
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


def instance_stats(instance: dict) -> dict[str, int]:
    """Return structural sizes that help explain scaling behaviour."""
    tasks = [
        task
        for flight_tasks, task_count in zip(
            instance["flight_tasks"], instance["flight_n_tasks"], strict=True
        )
        for task in flight_tasks[:task_count]
    ]
    task_kinds = Counter(TASK_TO_TEAM_KIND[task["kind"]] for task in tasks)
    available_team_kinds = set(instance["labor_kind"])

    # C9 creates one optional occurrence of each task for every compatible
    # team. This is a useful proxy for the size of its no-overlap inputs.
    c9_task_occurrences = sum(
        count * sum(team_kind == required_kind for team_kind in instance["labor_kind"])
        for required_kind, count in task_kinds.items()
    )

    return {
        "flights": len(instance["FlightID"]),
        "gates": len(instance["GateID"]),
        "teams": len(instance["LaborID"]),
        "tasks": len(tasks),
        # The old pairwise representation needed one directed candidate for
        # each task pair. This is retained as a comparison metric only.
        "legacy_c11_pairs": len(tasks) * (len(tasks) - 1),
        "c9_task_occurrences": c9_task_occurrences,
    }


def disabled_for_variant(variant: str) -> set[str]:
    normalized = variant.strip().lower()
    if normalized in {"baseline", "full"}:
        return set()
    if normalized.startswith("no-"):
        return {normalized[3:].upper()}
    raise ValueError(
        f"unknown variant {variant!r}; use baseline or a name such as no-c11"
    )


def measure(
    instance: dict,
    stats: dict[str, int],
    variant: str,
    time_limit: float | None,
    workers: int,
    build_only: bool,
) -> dict[str, object]:
    timing: dict[str, object] = {}
    started = time.perf_counter()
    try:
        # Suppress progress and solver output so I/O does not contaminate timing.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            solution = starter.solve(
                instance,
                disabled_constraints=disabled_for_variant(variant),
                show_progress=False,
                timing=timing,
                time_limit=time_limit,
                solver_options={"random_seed": 0, "num_workers": workers},
                build_only=build_only,
            )

        total_s = time.perf_counter() - started
        if build_only:
            return {
                **stats,
                "variant": variant,
                "status": "build_only",
                "build_s": timing.get("build_s"),
                "solver_s": 0.0,
                "total_s": total_s,
                "cost": None,
                "c11_predecessor_vars": timing.get("c11_predecessor_vars"),
            }

        expected_tasks = stats["tasks"]
        valid_shape = (
            len(solution["gate"]) == stats["flights"]
            and sum(map(len, solution["task_start"])) == expected_tasks
            and sum(map(len, solution["task_labor"])) == expected_tasks
        )
        status = str(timing.get("solver_status", "unknown"))
        return {
            **stats,
            "variant": variant,
            "status": status if valid_shape else "decode_error",
            "build_s": timing.get("build_s"),
            "solver_s": timing.get("solver_s"),
            "total_s": total_s,
            "cost": solution.get("cost"),
            "c11_predecessor_vars": timing.get("c11_predecessor_vars"),
        }
    except Exception as error:
        return {
            **stats,
            "variant": variant,
            "status": f"error:{type(error).__name__}",
            "build_s": timing.get("build_s"),
            "solver_s": timing.get("solver_s"),
            "total_s": time.perf_counter() - started,
            "cost": None,
            "error": str(error),
            "c11_predecessor_vars": timing.get("c11_predecessor_vars"),
        }


def median_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    result = dict(rows[0])
    result["runs"] = len(rows)
    for field in ("build_s", "solver_s", "total_s"):
        values = [float(row[field]) for row in rows if row[field] is not None]
        result[field] = statistics.median(values) if values else None
    result["statuses"] = "/".join(sorted({str(row["status"]) for row in rows}))
    result["costs"] = sorted(
        {str(row["cost"]) for row in rows if row["cost"] is not None}
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "instances",
        type=Path,
        nargs="*",
        help="instance files; defaults to data/hackathon_*.json",
    )
    parser.add_argument(
        "--variants",
        default="baseline,no-c11",
        help="comma-separated variants, e.g. baseline,no-c11,no-c9",
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--time-limit",
        type=float,
        default=5.0,
        help="CP-SAT seconds per run; use 0 for no limit",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="fixed CP-SAT worker count for reproducibility",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="optional JSON output path; CSV is written alongside it",
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="build each model but skip backend translation and solving",
    )
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.time_limit < 0:
        parser.error("--time-limit must be non-negative")
    if args.workers < 1:
        parser.error("--workers must be at least 1")

    paths = args.instances or sorted(Path("data").glob("hackathon_*.json"))
    if not paths:
        parser.error("no instance files found")

    variants = [variant.strip() for variant in args.variants.split(",") if variant.strip()]
    if not variants:
        parser.error("--variants must contain at least one variant")
    for variant in variants:
        try:
            disabled_for_variant(variant)
        except ValueError as error:
            parser.error(str(error))

    time_limit = args.time_limit or None
    rows: list[dict[str, object]] = []

    for path in paths:
        instance = json.loads(path.read_text())
        stats = instance_stats(instance)
        stats_with_name = {**stats, "instance": path.name}
        print(
            f"{path.name}: flights={stats['flights']} tasks={stats['tasks']} "
            f"gates={stats['gates']} teams={stats['teams']} "
            f"legacy_c11_pairs={stats['legacy_c11_pairs']}",
            flush=True,
        )
        for variant in variants:
            print(f"  running {variant}...", flush=True)
            samples = [
                measure(
                    instance,
                    stats_with_name,
                    variant,
                    time_limit,
                    args.workers,
                    args.build_only,
                )
                for _ in range(args.repeats)
            ]
            rows.append(median_rows(samples))

    print()
    print(
        f"workers={args.workers} repeats={args.repeats} "
        f"time_limit={'none' if time_limit is None else f'{time_limit:g}s'}"
    )
    print(
        "instance             variant     tasks teams legacy_pairs pred_vars "
        "status             build_s solver_s total_s"
    )
    for row in rows:
        def format_seconds(value: object) -> str:
            return "-" if value is None else f"{float(value):7.3f}"

        print(
            f"{str(row['instance']):<20} {str(row['variant']):<11} "
            f"{row['tasks']:>5} {row['teams']:>5} {row['legacy_c11_pairs']:>12} "
            f"{str(row['c11_predecessor_vars']):>8} "
            f"{str(row['statuses']):<18} "
            f"{format_seconds(row['build_s'])} "
            f"{format_seconds(row['solver_s'])} "
            f"{format_seconds(row['total_s'])}"
        )

    if args.output is not None:
        args.output.write_text(json.dumps(rows, indent=2) + "\n")
        csv_path = args.output.with_suffix(".csv")
        fields = list(rows[0])
        with csv_path.open("w", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {args.output} and {csv_path}")


if __name__ == "__main__":
    main()
