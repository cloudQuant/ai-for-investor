"""Parameter-grid validation and optimization task submission."""

import itertools
import math
from collections.abc import Callable, Mapping
from decimal import Decimal, DecimalException, InvalidOperation
from pathlib import Path
from typing import Any

MAX_GRID_COMBINATIONS = 10_000
BEST_RESULT_TIE_BREAK = "lowest_trial_index"
SUPPORTED_OBJECTIVES = {"sharpe_ratio", "max_drawdown", "total_return"}
SUPPORTED_DIRECTIONS = {"maximize", "minimize"}


def _decimal_value(value: Any, *, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise ValueError(f"Parameter {name} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Parameter {name} must be a finite number") from exc
    if not result.is_finite():
        raise ValueError(f"Parameter {name} must be a finite number")
    return result


def _range_axis_count(
    name: str,
    spec: Mapping[str, Any],
    *,
    max_count: int | None = None,
) -> tuple[Decimal, Decimal, Decimal, str, int]:
    missing = {"start", "end", "step"}.difference(spec)
    if missing:
        raise ValueError(f"Parameter {name} is missing {', '.join(sorted(missing))}")

    start = _decimal_value(spec["start"], name=name)
    end = _decimal_value(spec["end"], name=name)
    step = _decimal_value(spec["step"], name=name)
    value_type = spec.get("type", "float")
    if not isinstance(value_type, str) or value_type not in {"int", "float"}:
        raise ValueError(f"Parameter {name} type must be 'int' or 'float'")
    if step <= 0:
        raise ValueError(f"Parameter {name} step must be positive")
    if start > end:
        raise ValueError(
            f"Parameter grid is empty because parameter {name} range start must not exceed end"
        )

    if value_type == "int" and any(
        value != value.to_integral_value() for value in (start, end, step)
    ):
        raise ValueError(f"Integer parameter {name} requires integer start, end, and step")

    try:
        span = end - start
        if max_count is not None and span >= step * max_count:
            raise ValueError(f"Parameter grid exceeds the {max_count} combination limit")
        count = int(span // step) + 1
    except DecimalException as exc:
        raise ValueError(f"Parameter {name} range cannot be represented safely") from exc
    return start, end, step, value_type, count


def count_param_grid_combinations(
    param_ranges: Mapping[str, Mapping[str, Any]],
    *,
    max_combinations: int = MAX_GRID_COMBINATIONS,
) -> int:
    """Validate ranged parameters and count combinations without allocating the grid."""
    if not isinstance(param_ranges, Mapping):
        raise ValueError("Parameter ranges must be a mapping")
    if max_combinations < 1:
        raise ValueError("Maximum combination count must be positive")

    total = 1
    axes: list[tuple[str, Mapping[str, Any]]] = []
    for name, raw_spec in param_ranges.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Parameter names must be non-empty strings")
        if not isinstance(raw_spec, Mapping):
            raise ValueError(f"Parameter {name} range must be a mapping")
        _, _, _, _, axis_count = _range_axis_count(name, raw_spec, max_count=max_combinations)
        if axis_count > max_combinations or total > max_combinations // axis_count:
            raise ValueError(f"Parameter grid exceeds the {max_combinations} combination limit")
        total *= axis_count
        axes.append((name, raw_spec))

    # Check output precision and floating-point progress only after the cap has
    # established that validating every generated value is bounded.
    for name, raw_spec in axes:
        start, _, step, value_type, axis_count = _range_axis_count(
            name, raw_spec, max_count=max_combinations
        )
        previous_numeric: float | None = None
        previous_rounded: float | None = None
        for index in range(axis_count):
            value = start + (step * index)
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(f"Parameter {name} values must remain finite")
            if previous_numeric is not None and numeric <= previous_numeric:
                raise ValueError(f"Parameter {name} step does not advance numerically")
            if value_type == "float":
                rounded = round(numeric, 6)
                if previous_rounded is not None and rounded <= previous_rounded:
                    raise ValueError(
                        f"Parameter {name} step does not advance at supported precision"
                    )
                previous_rounded = rounded
            previous_numeric = numeric

    return total


def count_value_grid_combinations(
    param_grid: Mapping[str, Any],
    *,
    max_combinations: int = MAX_GRID_COMBINATIONS,
) -> int:
    """Count explicit choice-grid combinations without materializing the product."""
    if not isinstance(param_grid, Mapping):
        raise ValueError("Parameter grid must be a mapping")
    if max_combinations < 1:
        raise ValueError("Maximum combination count must be positive")

    total = 1
    for name, values in param_grid.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Parameter names must be non-empty strings")
        if not isinstance(values, list | tuple):
            raise ValueError(f"Parameter {name} values must be a list")
        if not values:
            return 0
        if len(values) > max_combinations or total > max_combinations // len(values):
            raise ValueError(f"Parameter grid exceeds the {max_combinations} combination limit")
        total *= len(values)
    return total


def validate_param_bounds(param_bounds: Mapping[str, Mapping[str, Any]]) -> None:
    """Validate Bayesian numeric bounds before a task is created."""
    if not isinstance(param_bounds, Mapping) or not param_bounds:
        raise ValueError("Bayesian parameter bounds must be a non-empty mapping")
    for name, spec in param_bounds.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Parameter names must be non-empty strings")
        if not isinstance(spec, Mapping):
            raise ValueError(f"Parameter {name} bounds must be a mapping")
        value_type = spec.get("type")
        if value_type == "categorical":
            choices = spec.get("choices")
            if not isinstance(choices, list | tuple) or not choices:
                raise ValueError(f"Categorical parameter {name} requires choices")
            continue
        if not isinstance(value_type, str) or value_type not in {"int", "float"}:
            raise ValueError(f"Parameter {name} type must be 'int', 'float', or 'categorical'")
        if "min" not in spec or "max" not in spec:
            raise ValueError(f"Parameter {name} requires min and max bounds")
        lower = _decimal_value(spec["min"], name=name)
        upper = _decimal_value(spec["max"], name=name)
        if lower > upper:
            raise ValueError(f"Parameter {name} minimum must not exceed maximum")
        if value_type == "int" and any(
            value != value.to_integral_value() for value in (lower, upper)
        ):
            raise ValueError(f"Integer parameter {name} requires integer min and max bounds")


def validate_objective_settings(objective: str | None, direction: str | None) -> None:
    """Validate an optional, explicit optimization objective and direction."""
    if objective is None and direction is None:
        return
    if not isinstance(objective, str) or objective not in SUPPORTED_OBJECTIVES:
        raise ValueError(f"Objective must be one of: {', '.join(sorted(SUPPORTED_OBJECTIVES))}")
    if not isinstance(direction, str) or direction not in SUPPORTED_DIRECTIONS:
        raise ValueError("Direction must be 'maximize' or 'minimize'")


def generate_param_grid(
    param_ranges: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate a bounded Cartesian product from validated range specifications."""
    count_param_grid_combinations(param_ranges)
    keys: list[str] = []
    value_lists: list[list[int | float]] = []
    for name, spec in param_ranges.items():
        start, _, step, value_type, axis_count = _range_axis_count(
            name, spec, max_count=MAX_GRID_COMBINATIONS
        )
        values: list[int | float] = []
        if value_type == "int":
            values.extend(int(start + (step * index)) for index in range(axis_count))
        else:
            values.extend(round(float(start + (step * index)), 6) for index in range(axis_count))
        keys.append(name)
        value_lists.append(values)

    combinations = itertools.product(*value_lists)
    return [dict(zip(keys, combo, strict=True)) for combo in combinations]


def submit_optimization(
    strategy_id: str,
    param_ranges: dict[str, dict[str, Any]],
    n_workers: int = 4,
    task_id: str | None = None,
    persist_to_db: bool = True,
    artifact_root: str | None = None,
    objective: str | None = None,
    direction: str | None = None,
    *,
    get_strategy_dir: Callable[[str], Path],
    generate_param_grid_fn: Callable[
        [dict[str, dict[str, Any]]], list[dict[str, Any]]
    ] = generate_param_grid,
    set_task_fn: Callable[[str, dict[str, Any]], Any],
    build_initial_runtime_task_fn: Callable[..., dict[str, Any]],
    created_at_fn: Callable[[], str],
    running_status: str,
    thread_cls: Callable[..., Any],
    run_optimization_thread_fn: Callable[
        [str, str, list[dict[str, Any]], int, bool, str | None], Any
    ],
    task_id_factory: Callable[[], str],
    strategy_dir_override: str | Path | None = None,
) -> str:
    validate_objective_settings(objective, direction)
    count_param_grid_combinations(param_ranges)

    if strategy_dir_override:
        strategy_dir = Path(strategy_dir_override)
    else:
        strategy_dir = get_strategy_dir(strategy_id)
    if not (strategy_dir / "run.py").is_file():
        raise ValueError(f"Strategy {strategy_id} not found or missing run.py")

    grid = generate_param_grid_fn(param_ranges)
    if not grid:
        raise ValueError("Parameter grid is empty, please check parameter range settings")

    resolved_task_id = task_id or task_id_factory()
    set_task_fn(
        resolved_task_id,
        build_initial_runtime_task_fn(
            strategy_id=strategy_id,
            param_ranges=param_ranges,
            total=len(grid),
            n_workers=n_workers,
            created_at=created_at_fn(),
            status=running_status,
            objective=objective,
            direction=direction,
        ),
    )

    thread = thread_cls(
        target=run_optimization_thread_fn,
        args=(resolved_task_id, str(strategy_dir), grid, n_workers, persist_to_db, artifact_root),
        daemon=True,
    )
    thread.start()

    return resolved_task_id
