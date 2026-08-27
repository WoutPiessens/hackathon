"""Measure the effect of removing one model constraint family at a time.

Examples
--------
    .venv/bin/python profile_ablation.py data/hackathon_03.json --repeats 3

The timing covers model construction, CP-SAT solving, and solution decoding. The
progress callback is disabled so terminal I/O does not dominate the comparison.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import statistics
import time
from pathlib import Path

import starter

CONSTRAINTS = tuple(f"C{i}" for i in range(1, 11))
VARIANTS = ("baseline", *CONSTRAINTS, "OBJ")


def measure(
    instance: dict, disabled: set[str], time_limit: float | None
) -> dict[str, object]:
    timing: dict[str, object] = {}
    started = time.perf_counter()
    try:
        # Suppress the solver callback and any incidental output from solve().
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            solution = starter.solve(
                instance,
                disabled_constraints=disabled,
                show_progress=False,
                timing=timing,
                time_limit=time_limit,
                solver_options={"random_seed": 0},
            )
        elapsed = time.perf_counter() - started
        expected_tasks = sum(instance["flight_n_tasks"])
        valid_shape = (
            len(solution["gate"]) == len(instance["FlightID"])
            and sum(map(len, solution["task_start"])) == expected_tasks
            and sum(map(len, solution["task_labor"])) == expected_tasks
        )
        solver_status = timing.get("solver_status", "unknown")
        return {
            "status": solver_status if valid_shape else "decode_error",
            "elapsed_s": elapsed,
            "build_s": timing.get("build_s"),
            "solver_s": timing.get("solver_s"),
            "cost": solution["cost"],
            "optimal": solver_status == "optimal",
        }
    except Exception as error:
        return {
            "status": f"error: {type(error).__name__}",
            "elapsed_s": time.perf_counter() - started,
            "build_s": timing.get("build_s"),
            "solver_s": timing.get("solver_s"),
            "cost": None,
            "error": str(error),
        }


def summarize(samples: list[dict[str, object]]) -> dict[str, object]:
    successful = [
        sample
        for sample in samples
        if sample["status"] in {"optimal", "feasible"}
    ]
    result = {
        "status": "/".join(sorted({str(sample["status"]) for sample in samples})),
        "runs": len(samples),
        "elapsed_median_s": None,
        "elapsed_min_s": None,
        "build_median_s": None,
        "solver_median_s": None,
        "costs": sorted({str(sample["cost"]) for sample in successful}),
        "samples": samples,
    }
    if successful:
        for key, output_key in (
            ("elapsed_s", "elapsed_median_s"),
            ("build_s", "build_median_s"),
            ("solver_s", "solver_median_s"),
        ):
            values = [float(sample[key]) for sample in successful if sample[key] is not None]
            result[output_key] = statistics.median(values)
            if key == "elapsed_s":
                result["elapsed_min_s"] = min(values)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "instance",
        type=Path,
        nargs="?",
        default=Path("data/hackathon_03.json"),
    )
    parser.add_argument("--repeats", type=int, default=3, help="timed runs per variant")
    parser.add_argument(
        "--time-limit",
        type=float,
        default=10.0,
        help="CP-SAT limit per run in seconds (default: 10; use 0 for no limit)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="optional path for the full JSON results",
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.time_limit < 0:
        parser.error("--time-limit must be non-negative")
    time_limit = args.time_limit or None

    instance = json.loads(args.instance.read_text())
    results: dict[str, dict[str, object]] = {}
    for variant in VARIANTS:
        print(f"running {variant}...", flush=True)
        disabled = set() if variant == "baseline" else {variant}
        samples = [
            measure(instance, disabled, time_limit) for _ in range(args.repeats)
        ]
        results[variant] = summarize(samples)

    baseline = results["baseline"]["elapsed_median_s"]
    limit_text = "none" if time_limit is None else f"{time_limit:g}s"
    print(
        f"instance={args.instance} repeats={args.repeats} "
        f"progress_callback=off time_limit={limit_text} workers=default seed=0"
    )
    print("variant    status   median_s  min_s  speedup  delta_vs_base  cost")
    for variant in VARIANTS:
        row = results[variant]
        median = row["elapsed_median_s"]
        if isinstance(baseline, float) and isinstance(median, float):
            speedup = baseline / median
            delta = (baseline - median) / baseline * 100
            speedup_text = f"{speedup:7.2f}x"
            delta_text = f"{delta:>+7.1f}%"
        else:
            speedup_text = "      -"
            delta_text = "      -"
        print(
            f"{variant:<9} {row['status']!s:<8} "
            f"{median if isinstance(median, float) else float('nan'):8.3f} "
            f"{row['elapsed_min_s'] if isinstance(row['elapsed_min_s'], float) else float('nan'):6.3f} "
            f"{speedup_text} {delta_text} {row['costs']}"
        )

    if args.output is not None:
        args.output.write_text(json.dumps(results, indent=2) + "\n")
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
