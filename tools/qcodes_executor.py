from __future__ import annotations

import argparse
import builtins
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import qcodes as qc
import yaml

WIRING_MAP_PATH = Path("memory") / "wiring_map.yaml"
LOG_DIR = Path("measurement") / "operation"
LOG_FILE = LOG_DIR / "qcodes_executor.log"


def _setup_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("qcodes_executor")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


LOGGER = _setup_logger()


def load_wiring_map(path: str | Path = WIRING_MAP_PATH) -> Dict[str, Any]:
    wiring_path = Path(path)
    if not wiring_path.exists():
        raise FileNotFoundError(f"Wiring map not found: {wiring_path}")

    with wiring_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError("wiring_map.yaml root must be a mapping/dict")

    return data


def _extract_max_safe_voltage_from_wiring(wiring: Dict[str, Any]) -> Optional[float]:
    # Support both requested_wiring.lines and generic nested dictionaries.
    requested = wiring.get("requested_wiring")
    candidates = []

    if isinstance(requested, dict):
        lines = requested.get("lines")
        if isinstance(lines, dict):
            candidates.append(lines)

    candidates.append(wiring)

    found_limits = []
    for node in candidates:
        if not isinstance(node, dict):
            continue
        stack = [node]
        while stack:
            current = stack.pop()
            if not isinstance(current, dict):
                continue

            if "max_safe_voltage" in current:
                try:
                    found_limits.append(float(current["max_safe_voltage"]))
                except (TypeError, ValueError):
                    continue

            for value in current.values():
                if isinstance(value, dict):
                    stack.append(value)

    if not found_limits:
        return None

    # Use the strictest limit if multiple entries exist.
    return min(found_limits)


def _read_parameter_value(parameter: Any) -> float:
    if hasattr(parameter, "get") and callable(parameter.get):
        return float(parameter.get())
    if hasattr(parameter, "__call__") and callable(parameter):
        return float(parameter())
    raise TypeError("Parameter object must provide callable get() or __call__()")


def _write_parameter_value(parameter: Any, value: float) -> None:
    if hasattr(parameter, "set") and callable(parameter.set):
        parameter.set(value)
        return
    if hasattr(parameter, "__call__") and callable(parameter):
        parameter(value)
        return
    raise TypeError("Parameter object must provide callable set() or __call__(value)")


def _print_iv_warning(target_voltage: float) -> None:
    message = (
        f"【IV级权限警告】即将修改直流偏置至 {target_voltage:.6g} V，"
        "请连续输入两次 'CONFIRM-DC' 以授权执行。"
    )
    # ANSI red text; terminals without ANSI support will still show readable warning text.
    print(f"\033[91m{message}\033[0m")


def safe_set_dc_bias(
    parameter: Any,
    target_voltage: float,
    step: float,
    max_safe_voltage: float,
) -> float:
    """
    IV-level secure DC bias setter.

    Safety checks:
    1. Read dynamic max_safe_voltage from memory/wiring_map.yaml if available.
    2. Enforce stricter limit between function argument and wiring map value.
    3. Require double terminal confirmation: CONFIRM-DC twice.
    4. Ramp to target with incremental step and short delay.

    Returns:
        Final voltage value read from parameter.
    """
    target_voltage = float(target_voltage)
    step = float(step)
    arg_limit = float(max_safe_voltage)

    if step <= 0:
        raise ValueError("step must be a positive float")

    wiring_limit: Optional[float] = None
    try:
        wiring_data = load_wiring_map()
        wiring_limit = _extract_max_safe_voltage_from_wiring(wiring_data)
    except FileNotFoundError:
        LOGGER.warning("wiring_map.yaml not found; fallback to provided max_safe_voltage only")
    except Exception as exc:
        LOGGER.warning("Failed to parse wiring_map.yaml, fallback to provided max_safe_voltage: %s", exc)

    effective_limit = arg_limit if wiring_limit is None else min(arg_limit, wiring_limit)

    if abs(target_voltage) > abs(effective_limit):
        raise PermissionError(
            f"Target voltage {target_voltage:.6g} V exceeds max safe voltage {effective_limit:.6g} V"
        )

    _print_iv_warning(target_voltage)
    first = input("请输入第1次确认: ").strip()
    second = input("请输入第2次确认: ").strip()

    if first != "CONFIRM-DC" or second != "CONFIRM-DC":
        raise PermissionError("IV-level authorization failed: confirmation mismatch")

    current = _read_parameter_value(parameter)
    delta = target_voltage - current
    if abs(delta) < 1e-15:
        LOGGER.info("DC bias unchanged at %.9f V", current)
        return current

    direction = 1.0 if delta > 0 else -1.0
    n_steps = max(1, int(abs(delta) / step))
    delay_s = 0.05

    LOGGER.info(
        "Starting DC ramp: current=%.9f V, target=%.9f V, step=%.6g V, max_safe=%.6g V, steps=%d",
        current,
        target_voltage,
        step,
        effective_limit,
        n_steps,
    )

    for i in range(1, n_steps + 1):
        next_value = current + direction * min(abs(delta), i * step)
        if abs(next_value) > abs(effective_limit):
            raise PermissionError(
                f"Ramp aborted at step {i}: value {next_value:.6g} V exceeds limit {effective_limit:.6g} V"
            )
        _write_parameter_value(parameter, next_value)
        time.sleep(delay_s)

    _write_parameter_value(parameter, target_voltage)
    final_value = _read_parameter_value(parameter)
    LOGGER.info("DC ramp completed: final=%.9f V", final_value)
    return final_value


def safe_set_dc_bias_from_wiring(
    parameter: Any,
    target_voltage: float,
    step: float,
) -> float:
    wiring_data = load_wiring_map()
    wiring_limit = _extract_max_safe_voltage_from_wiring(wiring_data)
    if wiring_limit is None:
        raise PermissionError("max_safe_voltage not found in memory/wiring_map.yaml")
    return safe_set_dc_bias(parameter, target_voltage, step, wiring_limit)


def _extract_estimated_duration_minutes(source: str) -> Optional[float]:
    patterns = [
        r"ESTIMATED_DURATION_MIN\s*=\s*([0-9]+(?:\.[0-9]+)?)",
        r"estimated_duration_min\s*=\s*([0-9]+(?:\.[0-9]+)?)",
        r"ESTIMATED_DURATION_MIN\s*:\s*([0-9]+(?:\.[0-9]+)?)",
    ]
    for p in patterns:
        m = re.search(p, source)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def execute_agent_script(script_path: str) -> None:
    """
    Execute an AI-agent generated temporary measurement script in a restricted context.

    The execution context injects safe_set_dc_bias wrappers and blocks direct access to
    unnecessary builtins, while still allowing common Python script operations.
    """
    path = Path(script_path)
    if not path.exists():
        raise FileNotFoundError(f"Script not found: {path}")

    source = path.read_text(encoding="utf-8")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    started = time.time()
    est_min = _extract_estimated_duration_minutes(source)

    LOGGER.info("Run %s started: script=%s", run_id, path)
    if est_min is not None:
        LOGGER.info("Run %s estimated runtime: %.2f min", run_id, est_min)
    else:
        LOGGER.info("Run %s estimated runtime: unknown", run_id)

    safe_builtins = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "print": print,
        "range": range,
        "set": set,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
        "Exception": Exception,
        "PermissionError": PermissionError,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "RuntimeError": RuntimeError,
        "__import__": builtins.__import__,
    }

    restricted_globals: Dict[str, Any] = {
        "__name__": "__agent_script__",
        "__file__": str(path),
        "__builtins__": safe_builtins,
        "qc": qc,
        "logging": logging,
        "safe_set_dc_bias": safe_set_dc_bias,
        "safe_set_dc_bias_from_wiring": safe_set_dc_bias_from_wiring,
        "load_wiring_map": load_wiring_map,
    }

    try:
        compiled = compile(source, str(path), "exec")
        exec(compiled, restricted_globals, restricted_globals)
    except Exception:
        elapsed = time.time() - started
        LOGGER.exception("Run %s failed after %.2f s", run_id, elapsed)
        raise

    elapsed = time.time() - started
    LOGGER.info("Run %s completed successfully in %.2f s", run_id, elapsed)


def main() -> None:
    parser = argparse.ArgumentParser(description="QCoDeS measurement executor with IV safety lock")
    parser.add_argument("script_path", help="Path to agent-generated script")
    args = parser.parse_args()

    execute_agent_script(args.script_path)


if __name__ == "__main__":
    main()
