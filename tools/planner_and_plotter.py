from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from string import ascii_uppercase
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle


DEFAULT_OUTPUT_DIR = os.path.join("measurement", "operation")


@dataclass
class PulseItem:
    qubit_name: str
    role: str
    pulse_index: int
    pulse_name: str
    shape: str
    start_ns: float
    width_ns: float
    amp: float
    freq_hz: Optional[float]
    phase_deg: Optional[float]
    scan_symbol: Optional[str] = None


def _ensure_parent_dir(file_path: str) -> None:
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _sec_or_ns_to_ns(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Cannot convert value '{value}' to float") from exc

    # If magnitude is less than 1e-3, treat as seconds and convert to ns.
    if abs(v) < 1e-3:
        return v * 1e9
    return v


def _extract_channel_waveform_bank(channel_cfg: Dict[str, Any]) -> Dict[str, List[Any]]:
    waveform_bank = channel_cfg.get("waveform_bank")
    if waveform_bank is None:
        waveform_bank = {
            "shape_list": channel_cfg.get("shape_list", []),
            "pw_list": channel_cfg.get("pw_list", []),
            "ew_list": channel_cfg.get("ew_list", []),
            "amp_list": channel_cfg.get("amp_list", []),
            "center_list": channel_cfg.get("center_list", []),
            "phase_list": channel_cfg.get("phase_list", []),
            "freq_list": channel_cfg.get("freq_list", []),
        }

    required_keys = [
        "shape_list",
        "pw_list",
        "ew_list",
        "amp_list",
        "center_list",
        "phase_list",
        "freq_list",
    ]
    for key in required_keys:
        if key not in waveform_bank:
            raise ValueError(f"waveform_bank missing key: {key}")
        if not isinstance(waveform_bank[key], list):
            raise ValueError(f"waveform_bank[{key}] must be a list")

    length_set = {len(waveform_bank[k]) for k in required_keys}
    if len(length_set) != 1:
        raise ValueError("All 7 waveform lists must have the same length")

    return waveform_bank


def _build_scan_symbol_map(scan_parameters: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[Tuple[str, str, int, str], str]]:
    normalized: List[Dict[str, Any]] = []
    lookup: Dict[Tuple[str, str, int, str], str] = {}

    for idx, item in enumerate(scan_parameters):
        if not isinstance(item, dict):
            raise ValueError("Each scan parameter must be a dict")

        symbol = item.get("symbol")
        if not symbol:
            if idx >= len(ascii_uppercase):
                raise ValueError("Too many scan parameters; symbol not provided")
            symbol = ascii_uppercase[idx]

        where = item.get("where", {})
        qubit = str(where.get("qubit", ""))
        role = str(where.get("role", "")).lower()
        pulse_index = int(where.get("pulse_index", -1))
        field = str(where.get("field", "")).lower()

        normalized_item = {
            "symbol": symbol,
            "name": item.get("name", "unknown"),
            "range": item.get("range"),
            "step": item.get("step"),
            "num_points": item.get("num_points"),
            "values": item.get("values"),
            "where": {
                "qubit": qubit,
                "role": role,
                "pulse_index": pulse_index,
                "field": field,
            },
        }
        normalized.append(normalized_item)

        if qubit and role and pulse_index >= 0 and field:
            lookup[(qubit, role, pulse_index, field)] = symbol

    return normalized, lookup


def _expand_channel_pulses(
    qubit_name: str,
    role: str,
    channel_cfg: Dict[str, Any],
    scan_lookup: Dict[Tuple[str, str, int, str], str],
    qubit_idx: int,
) -> List[PulseItem]:
    waveform_bank = _extract_channel_waveform_bank(channel_cfg)

    shape_list = waveform_bank["shape_list"]
    pw_list = waveform_bank["pw_list"]
    amp_list = waveform_bank["amp_list"]
    phase_list = waveform_bank["phase_list"]
    freq_list = waveform_bank["freq_list"]

    start_list_raw = channel_cfg.get("start_list", [])
    delay_ns = _sec_or_ns_to_ns(channel_cfg.get("delay_ns", channel_cfg.get("delay", 0.0)))
    spacing_ns = _sec_or_ns_to_ns(channel_cfg.get("spacing_ns", channel_cfg.get("spacing_time", 0.0)))

    pulses: List[PulseItem] = []
    cursor = delay_ns

    for i in range(len(shape_list)):
        width_ns = _sec_or_ns_to_ns(pw_list[i])
        if i < len(start_list_raw):
            start_ns = _sec_or_ns_to_ns(start_list_raw[i])
        else:
            start_ns = cursor
            cursor = start_ns + width_ns + spacing_ns

        shape = str(shape_list[i]).lower()
        amp = float(amp_list[i])
        freq = None if freq_list[i] is None else float(freq_list[i])
        phase = None if phase_list[i] is None else float(phase_list[i])

        pulse_name = f"ch#{qubit_idx + 1}{role}#{i + 1}"

        scan_symbol = None
        for field in ("amp", "freq", "phase", "width", "start"):
            key = (qubit_name, role, i, field)
            if key in scan_lookup:
                scan_symbol = scan_lookup[key]
                break

        pulses.append(
            PulseItem(
                qubit_name=qubit_name,
                role=role,
                pulse_index=i,
                pulse_name=pulse_name,
                shape=shape,
                start_ns=start_ns,
                width_ns=width_ns,
                amp=amp,
                freq_hz=freq,
                phase_deg=phase,
                scan_symbol=scan_symbol,
            )
        )

    return pulses


def _draw_square_pulse(ax: Any, x_start: float, x_width: float, amp: float, y_base: float, color: str) -> None:
    height = amp if amp != 0 else 0.1
    ax.add_patch(
        Rectangle(
            (x_start, y_base),
            x_width,
            height,
            facecolor=color,
            edgecolor="black",
            linewidth=0.8,
            alpha=0.75,
        )
    )


def _draw_gaussian_pulse(
    ax: Any,
    x_start: float,
    x_width: float,
    amp: float,
    y_base: float,
    color: str,
    direction: int,
) -> None:
    sigma = max(x_width / 6.0, 1e-6)
    x = np.linspace(x_start, x_start + x_width, 160)
    center = x_start + x_width / 2.0
    env = amp * np.exp(-0.5 * ((x - center) / sigma) ** 2)
    y_wave = y_base + direction * env
    ax.plot(x, y_wave, color=color, linewidth=1.6)
    ax.fill_between(x, y_base, y_wave, color=color, alpha=0.28)


def _text_lane(lanes: List[float], x_start: float, x_span: float) -> int:
    for idx, lane_end in enumerate(lanes):
        if x_start >= lane_end:
            lanes[idx] = x_start + x_span
            return idx
    lanes.append(x_start + x_span)
    return len(lanes) - 1


def _annotate_pulse(
    ax: Any,
    pulse: PulseItem,
    x_start: float,
    x_width: float,
    y_base: float,
    top_lanes: List[float],
    axis_lanes: List[float],
) -> None:
    amp_draw = max(abs(pulse.amp), 0.12)
    is_above = y_base >= 0
    y_top = y_base + amp_draw if is_above else y_base + amp_draw
    y_bottom = y_base if is_above else y_base
    mid_x = x_start + x_width / 2.0

    width_text = f"{pulse.width_ns:.1f} ns"
    amp_text = f"amp={pulse.amp:.3g}"
    if pulse.scan_symbol:
        amp_text = f"{amp_text} ({pulse.scan_symbol})"

    inner_y = y_bottom + (0.45 * amp_draw)
    ax.text(mid_x, inner_y, width_text, fontsize=8, ha="center", va="center")

    label_span = max(0.6, x_width * 0.55)
    top_lane = _text_lane(top_lanes, x_start, label_span)
    top_shift = 0.17 * top_lane

    if is_above:
        amp_y = y_top + 0.08 + top_shift
        name_y = y_top + 0.2 + top_shift
        amp_va = "bottom"
        name_va = "bottom"
    else:
        amp_y = 0.0 - 0.08 - top_shift
        name_y = 0.0 - 0.22 - top_shift
        amp_va = "top"
        name_va = "top"

    ax.text(x_start, amp_y, amp_text, fontsize=8, ha="left", va=amp_va)
    ax.text(mid_x, name_y, pulse.pulse_name, fontsize=8, ha="center", va=name_va)

    axis_span = max(0.45, 0.045 * len(f"t0={pulse.start_ns:.1f}"))
    axis_lane = _text_lane(axis_lanes, x_start, axis_span)
    axis_shift = 0.1 * axis_lane
    ax.text(x_start, -0.08 - axis_shift, f"t0={pulse.start_ns:.1f}", fontsize=7, ha="left", va="top")


def _visual_width(width_ns: float, ref_width_ns: float) -> float:
    safe_w = max(width_ns, ref_width_ns)
    return ref_width_ns * (1.0 + np.log10(safe_w / ref_width_ns))


def _time_to_visual(time_ns: float, ref_width_ns: float, x_scale: float = 6.0) -> float:
    safe_t = max(time_ns, 0.0)
    return ref_width_ns * x_scale * np.log10(1.0 + safe_t / ref_width_ns)


def _collect_frequency_palette(all_pulses: List[PulseItem]) -> Dict[float, str]:
    freqs = sorted({p.freq_hz for p in all_pulses if p.role == "drive" and p.freq_hz is not None})
    if not freqs:
        return {}

    cmap = plt.cm.get_cmap("tab10", max(len(freqs), 1))
    palette: Dict[float, str] = {}
    for i, freq in enumerate(freqs):
        palette[freq] = cmap(i)
    return palette


def plot_pulse_sequence(sequence_dict: Dict[str, Any], save_path: str) -> str:
    """
    Plot pulse sequence per qubit axis.

    The X axis is time in ns. Drive pulses are shown above the baseline.
    Z pulses and readout pulses are shown below the baseline.
    Acquisition windows are shown above the baseline.

    Returns:
        The saved figure path.
    """
    if not isinstance(sequence_dict, dict):
        raise ValueError("sequence_dict must be a dict")

    qubits = sequence_dict.get("qubits", [])
    if not isinstance(qubits, list) or not qubits:
        raise ValueError("sequence_dict['qubits'] must be a non-empty list")

    scan_parameters = sequence_dict.get("scan_parameters", [])
    normalized_scan, scan_lookup = _build_scan_symbol_map(scan_parameters)

    qubit_pulses: List[List[PulseItem]] = []
    all_pulses: List[PulseItem] = []

    for q_idx, q_cfg in enumerate(qubits):
        if not isinstance(q_cfg, dict):
            raise ValueError("Each qubit config must be a dict")

        qubit_name = str(q_cfg.get("name", f"q{q_idx + 1}"))
        per_qubit: List[PulseItem] = []

        if isinstance(q_cfg.get("xy"), dict):
            per_qubit.extend(
                _expand_channel_pulses(qubit_name, "drive", q_cfg["xy"], scan_lookup, q_idx)
            )

        if isinstance(q_cfg.get("z"), dict):
            per_qubit.extend(
                _expand_channel_pulses(qubit_name, "z", q_cfg["z"], scan_lookup, q_idx)
            )

        if isinstance(q_cfg.get("readout"), dict):
            per_qubit.extend(
                _expand_channel_pulses(qubit_name, "readout", q_cfg["readout"], scan_lookup, q_idx)
            )

        qubit_pulses.append(per_qubit)
        all_pulses.extend(per_qubit)

    freq_palette = _collect_frequency_palette(all_pulses)

    n_qubits = len(qubits)
    fig, axes = plt.subplots(n_qubits, 1, figsize=(14, max(3.2 * n_qubits, 4.0)), sharex=True)
    if n_qubits == 1:
        axes = [axes]

    all_widths = [max(1e-6, p.width_ns) for p in all_pulses]
    ref_width_ns = min(all_widths) if all_widths else 1.0
    vis_t_max = 0.0

    for q_idx, ax in enumerate(axes):
        q_name = str(qubits[q_idx].get("name", f"q{q_idx + 1}"))
        ax.axhline(0.0, color="black", linewidth=1.1)
        ax.set_title(f"Qubit: {q_name}", fontsize=11)
        ax.set_ylabel("Amp")
        ax.grid(False)
        ax.set_xticks([])
        ax.tick_params(axis="x", which="both", bottom=False, top=False, labelbottom=False)
        ax.spines["bottom"].set_visible(True)

        top_lanes: List[float] = []
        axis_lanes: List[float] = []

        pulses = qubit_pulses[q_idx]
        for pulse in pulses:
            amp_draw = max(abs(pulse.amp), 0.12)
            if pulse.role == "drive":
                y_base = 0.0
                direction = 1
                if pulse.freq_hz is not None and pulse.freq_hz in freq_palette:
                    color = freq_palette[pulse.freq_hz]
                else:
                    color = "tab:blue"
            elif pulse.role == "z":
                y_base = -amp_draw
                direction = 1
                color = "tab:green"
            else:
                y_base = -amp_draw
                direction = 1
                color = "tab:orange"

            x_start = _time_to_visual(pulse.start_ns, ref_width_ns)
            x_width = _visual_width(pulse.width_ns, ref_width_ns)
            vis_t_max = max(vis_t_max, x_start + x_width)

            if pulse.shape.startswith("gauss"):
                if pulse.role == "drive":
                    _draw_gaussian_pulse(ax, x_start, x_width, amp_draw, y_base, color, direction=1)
                else:
                    _draw_gaussian_pulse(ax, x_start, x_width, amp_draw, 0.0, color, direction=-1)
            else:
                if pulse.role == "drive":
                    _draw_square_pulse(ax, x_start, x_width, amp_draw, y_base, color)
                else:
                    _draw_square_pulse(ax, x_start, x_width, amp_draw, -amp_draw, color)

            _annotate_pulse(ax, pulse, x_start, x_width, y_base, top_lanes, axis_lanes)

        acq = qubits[q_idx].get("acquisition")
        if isinstance(acq, dict):
            acq_start = _sec_or_ns_to_ns(acq.get("start_ns", acq.get("start", 0.0)))
            acq_len = _sec_or_ns_to_ns(acq.get("length_ns", acq.get("length", 0.0)))
            acq_start_vis = _time_to_visual(acq_start, ref_width_ns)
            acq_len_vis = _visual_width(acq_len, ref_width_ns)
            ax.add_patch(
                Rectangle(
                    (acq_start_vis, 0.0),
                    acq_len_vis,
                    0.16,
                    facecolor="none",
                    edgecolor="tab:red",
                    linestyle="--",
                    linewidth=1.1,
                )
            )
            ax.text(
                acq_start_vis,
                0.2,
                f"acq: {acq_start:.1f} to {acq_start + acq_len:.1f} ns",
                color="tab:red",
                fontsize=8,
                ha="left",
                va="bottom",
            )
            vis_t_max = max(vis_t_max, acq_start_vis + acq_len_vis)

        ax.set_ylim(-1.5, 1.6)

    axes[-1].set_xlabel("Time (log-compressed visual axis, start labels in ns)")
    for ax in axes:
        ax.set_xlim(0.0, max(10.0, vis_t_max * 1.08))

    if normalized_scan:
        scan_lines = []
        for item in normalized_scan:
            desc = f"{item['symbol']}: {item['name']}"
            if item.get("range") is not None:
                desc += f", range={item['range']}"
            if item.get("step") is not None:
                desc += f", step={item['step']}"
            if item.get("num_points") is not None:
                desc += f", points={item['num_points']}"
            scan_lines.append(desc)

        fig.text(
            0.01,
            0.01,
            "Scan symbols | " + " ; ".join(scan_lines),
            fontsize=8,
            ha="left",
            va="bottom",
        )

    if freq_palette:
        legend_lines = [f"{freq / 1e9:.6f} GHz" for freq in sorted(freq_palette)]
        axes[0].text(
            0.995,
            0.98,
            "Drive freq color map: " + ", ".join(legend_lines),
            fontsize=8,
            ha="right",
            va="top",
            transform=axes[0].transAxes,
        )

    _ensure_parent_dir(save_path)
    fig.tight_layout(rect=(0.0, 0.03, 1.0, 1.0))
    fig.savefig(save_path, dpi=180)
    plt.close(fig)
    return save_path


def plot_parameter_sweep(sweep_config: Dict[str, Any], save_path: str) -> str:
    """
    Write scan summary and pulse/readout details to JSON.

    Note:
        This function intentionally does not draw a parameter sweep figure.
        It serializes scan and pulse details for downstream AI-agent parsing.

    Returns:
        The saved JSON path.
    """
    if not isinstance(sweep_config, dict):
        raise ValueError("sweep_config must be a dict")

    sequence_dict = sweep_config.get("sequence_dict")
    if not isinstance(sequence_dict, dict):
        raise ValueError("sweep_config must contain key 'sequence_dict' as dict")

    qubits = sequence_dict.get("qubits", [])
    if not isinstance(qubits, list) or not qubits:
        raise ValueError("sequence_dict['qubits'] must be a non-empty list")

    scan_parameters = sequence_dict.get("scan_parameters", sweep_config.get("scan_parameters", []))
    normalized_scan, _ = _build_scan_symbol_map(scan_parameters)

    summary_qubits: List[Dict[str, Any]] = []
    text_lines: List[str] = []
    total_points = 1

    for item in normalized_scan:
        if item.get("num_points") is not None:
            total_points *= max(1, int(item["num_points"]))
        elif isinstance(item.get("values"), list):
            total_points *= max(1, len(item["values"]))

    for q_idx, q_cfg in enumerate(qubits):
        q_name = str(q_cfg.get("name", f"q{q_idx + 1}"))
        q_out: Dict[str, Any] = {"name": q_name}

        for role_key in ("xy", "z", "readout"):
            role_cfg = q_cfg.get(role_key)
            if isinstance(role_cfg, dict):
                waveform_bank = _extract_channel_waveform_bank(role_cfg)
                q_out[f"{role_key}_waveform_bank"] = waveform_bank

        ro_cfg = q_cfg.get("readout")
        if isinstance(ro_cfg, dict):
            q_out["readout_timing"] = {
                "delay": ro_cfg.get("delay", ro_cfg.get("delay_ns")),
                "in_delay": ro_cfg.get("in_delay", ro_cfg.get("in_delay_ns")),
                "sample_length": ro_cfg.get("sample_length", ro_cfg.get("sample_length_ns")),
                "shots": ro_cfg.get("shots"),
                "period": ro_cfg.get("period"),
            }

        acq_cfg = q_cfg.get("acquisition")
        if isinstance(acq_cfg, dict):
            q_out["acquisition_window_ns"] = {
                "start_ns": _sec_or_ns_to_ns(acq_cfg.get("start_ns", acq_cfg.get("start", 0.0))),
                "length_ns": _sec_or_ns_to_ns(acq_cfg.get("length_ns", acq_cfg.get("length", 0.0))),
            }

        summary_qubits.append(q_out)
        text_lines.append(f"{q_name}: channels={', '.join([k for k in ('xy', 'z', 'readout') if isinstance(q_cfg.get(k), dict)])}")

    safety_limits = sweep_config.get("safety_limits", {})
    if isinstance(safety_limits, dict) and "max_safe_voltage" in safety_limits:
        text_lines.append(f"Safety max_safe_voltage={safety_limits['max_safe_voltage']}")

    text_lines.append(f"Estimated measurement points={total_points}")

    result: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary_text": " | ".join(text_lines),
        "scan_parameters": normalized_scan,
        "estimated_points": total_points,
        "safety_limits": safety_limits,
        "qubits": summary_qubits,
    }

    _ensure_parent_dir(save_path)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return save_path


def visualize_and_confirm(
    sweep_config: Dict[str, Any],
    sequence_dict: Dict[str, Any],
    output_dir: str = DEFAULT_OUTPUT_DIR,
    interactive: bool = True,
) -> bool:
    """
    Generate pulse-sequence figure + scan summary JSON, then ask for manual confirmation.

    Returns:
        True only if confirmation is Y/y.
    """
    try:
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fig_path = os.path.join(output_dir, f"pulse_sequence_{timestamp}.png")
        json_path = os.path.join(output_dir, f"operation_summary_{timestamp}.json")

        seq_copy = dict(sequence_dict)
        if "scan_parameters" not in seq_copy and "scan_parameters" in sweep_config:
            seq_copy["scan_parameters"] = sweep_config["scan_parameters"]

        saved_fig = plot_pulse_sequence(seq_copy, fig_path)

        combined = dict(sweep_config)
        combined["sequence_dict"] = seq_copy
        saved_json = plot_parameter_sweep(combined, json_path)

        print(f"时序图已保存: {saved_fig}")
        print(f"参数与脉冲信息 JSON 已保存: {saved_json}")

        if not interactive:
            return True

        answer = input("【人工确认】时序与扫描参数是否合理？(Y/N): ").strip().upper()
        return answer == "Y"

    except Exception as exc:
        print(f"visualize_and_confirm failed: {exc}")
        return False


__all__ = [
    "plot_parameter_sweep",
    "plot_pulse_sequence",
    "visualize_and_confirm",
]
