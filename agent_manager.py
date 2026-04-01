from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

MEMORY_DIR = Path("memory")
SHORT_TERM_PATH = Path("measurement") / "short_term_context.md"
TEMP_CACHE_PATH = MEMORY_DIR / "temp_experience_cache.md"
LONG_TERM_PATH = MEMORY_DIR / "long_term_skills.md"
WIRING_MAP_PATH = MEMORY_DIR / "wiring_map.yaml"

SHORT_TERM_TEMPLATE = """# 短期参数记忆

## 说明
- 本文件仅保存本轮测量参数，不保存硬件通道映射。
- 硬件通道统一从 memory/wiring_map.yaml 读取。

## 参数存档(JSON)
```json
{
    "last_update": null,
    "records": {}
}
```
"""

JSON_SECTION_TITLE = "参数存档(JSON)"


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _ensure_memory_files() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    SHORT_TERM_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not SHORT_TERM_PATH.exists():
        SHORT_TERM_PATH.write_text(SHORT_TERM_TEMPLATE, encoding="utf-8")

    if not TEMP_CACHE_PATH.exists():
        TEMP_CACHE_PATH.write_text("", encoding="utf-8")

    if not LONG_TERM_PATH.exists():
        LONG_TERM_PATH.write_text("# 长期经验库\n", encoding="utf-8")


def _load_markdown(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _default_short_term_store() -> Dict[str, Any]:
    return {
        "last_update": None,
        "records": {},
    }


def _extract_short_term_store(md: str) -> Dict[str, Any]:
    pattern = re.compile(
        rf"##\s+{re.escape(JSON_SECTION_TITLE)}\s*```json\s*(.*?)\s*```",
        re.DOTALL,
    )
    match = pattern.search(md)
    if not match:
        return _default_short_term_store()

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return _default_short_term_store()

    if not isinstance(data, dict):
        return _default_short_term_store()

    records = data.get("records", {})
    if not isinstance(records, dict):
        records = {}

    return {
        "last_update": data.get("last_update"),
        "records": records,
    }


def _write_short_term_store(store: Dict[str, Any]) -> None:
    payload = {
        "last_update": store.get("last_update"),
        "records": store.get("records", {}),
    }
    content = (
        "# 短期参数记忆\n\n"
        "## 说明\n"
        "- 本文件仅保存本轮测量参数，不保存硬件通道映射。\n"
        "- 硬件通道统一从 memory/wiring_map.yaml 读取。\n\n"
        "## 参数存档(JSON)\n"
        "```json\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        "```\n"
    )
    SHORT_TERM_PATH.write_text(content, encoding="utf-8")


def _load_short_term_store() -> Dict[str, Any]:
    md = _load_markdown(SHORT_TERM_PATH)
    if not md.strip():
        return _default_short_term_store()
    return _extract_short_term_store(md)


def _deep_merge_dict(base: Dict[str, Any], new_value: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in new_value.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def _ensure_section(md: str, section_title: str) -> str:
    pattern = re.compile(rf"(^##\s+{re.escape(section_title)}\s*$)(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
    if pattern.search(md):
        return md

    if not md.endswith("\n"):
        md += "\n"
    md += f"\n## {section_title}\n"
    return md


def _replace_section_body(md: str, section_title: str, body: str) -> str:
    pattern = re.compile(rf"(^##\s+{re.escape(section_title)}\s*$)(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)

    def repl(match: re.Match[str]) -> str:
        header = match.group(1)
        return f"{header}\n{body}\n"

    new_md, count = pattern.subn(repl, md, count=1)
    if count == 0:
        raise ValueError(f"Section not found after ensure: {section_title}")
    return new_md


def _parse_params_dict(raw: str) -> Dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("--params_dict 必须是 JSON 对象")
    return data


def _parse_task_status(raw: str) -> Dict[str, bool]:
    # Supported forms:
    # 1) JSON object: {"任务A": true, "任务B": false}
    # 2) JSON list: [{"task":"任务A", "done": true}, ...]
    # 3) Plain text: "任务A" (treated as done=true)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {raw.strip(): True} if raw.strip() else {}

    out: Dict[str, bool] = {}
    if isinstance(parsed, dict):
        for k, v in parsed.items():
            out[str(k)] = bool(v)
        return out

    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict) and "task" in item:
                out[str(item["task"])] = bool(item.get("done", True))
        return out

    raise ValueError("--task_status 仅支持 JSON 对象 / JSON 数组 / 纯文本任务名")


def _parse_nested_payload(raw: str) -> Dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("参数必须是 JSON 对象")
    return data


def _load_wiring_map() -> Dict[str, Any]:
    if not WIRING_MAP_PATH.exists():
        return {}
    with WIRING_MAP_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _select_wiring_for_qubits(wiring: Dict[str, Any], qubits: List[str]) -> Dict[str, Any]:
    qset = set(qubits)
    drive = wiring.get("drive_channels", [])
    readout = wiring.get("readout_channels", [])

    selected_drive = []
    if isinstance(drive, list):
        for item in drive:
            if not isinstance(item, dict):
                continue
            item_qubits = item.get("qubits", [])
            if isinstance(item_qubits, list) and qset.intersection(str(q) for q in item_qubits):
                selected_drive.append(item)

    selected_readout = []
    if isinstance(readout, list):
        for item in readout:
            if not isinstance(item, dict):
                continue
            serves = item.get("serves_qubits", [])
            if isinstance(serves, list) and qset.intersection(str(q) for q in serves):
                selected_readout.append(item)

    return {
        "drive_channels": selected_drive,
        "readout_channels": selected_readout,
    }


def _select_records(records: Dict[str, Any], requirements: Dict[str, Any]) -> Dict[str, Any]:
    if not requirements:
        return records

    output: Dict[str, Any] = {}
    for qubit, wanted in requirements.items():
        q_key = str(qubit)
        q_data = records.get(q_key)
        if not isinstance(q_data, dict):
            continue

        if wanted in ("*", None):
            output[q_key] = q_data
            continue

        if isinstance(wanted, str):
            wanted = [wanted]

        if not isinstance(wanted, list):
            continue

        selected: Dict[str, Any] = {}
        for key in wanted:
            if not isinstance(key, str):
                continue
            if key in q_data:
                selected[key] = q_data[key]
        if selected:
            output[q_key] = selected

    return output


def cmd_reset_short_term() -> Dict[str, Any]:
    _write_short_term_store(_default_short_term_store())
    return {
        "ok": True,
        "action": "reset_short_term",
        "file": str(SHORT_TERM_PATH),
    }


def cmd_save_short_term(params_raw: str) -> Dict[str, Any]:
    payload = _parse_nested_payload(params_raw)
    store = _load_short_term_store()
    records = store.get("records", {})
    if not isinstance(records, dict):
        records = {}

    records = _deep_merge_dict(records, payload)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    store["records"] = records
    store["last_update"] = ts
    _write_short_term_store(store)

    return {
        "ok": True,
        "action": "save_short_term",
        "file": str(SHORT_TERM_PATH),
        "saved_qubits": list(payload.keys()),
        "last_update": ts,
    }


def cmd_get_short_term(requirements_raw: str | None) -> Dict[str, Any]:
    store = _load_short_term_store()
    records = store.get("records", {}) if isinstance(store.get("records"), dict) else {}
    requirements: Dict[str, Any] = {}

    if requirements_raw:
        requirements = _parse_nested_payload(requirements_raw)

    selected = _select_records(records, requirements)
    return {
        "ok": True,
        "action": "get_short_term",
        "file": str(SHORT_TERM_PATH),
        "last_update": store.get("last_update"),
        "records": selected,
    }


def cmd_prepare_experiment_inputs(requirements_raw: str) -> Dict[str, Any]:
    requirements = _parse_nested_payload(requirements_raw)
    short_term = cmd_get_short_term(json.dumps(requirements, ensure_ascii=False))
    qubits = list(short_term.get("records", {}).keys())

    wiring = _load_wiring_map()
    wiring_selection = _select_wiring_for_qubits(wiring, qubits)

    return {
        "ok": True,
        "action": "prepare_experiment_inputs",
        "params_file": str(SHORT_TERM_PATH),
        "wiring_file": str(WIRING_MAP_PATH),
        "last_update": short_term.get("last_update"),
        "params": short_term.get("records", {}),
        "wiring": wiring_selection,
    }


def cmd_update_short_term(params_dict_raw: str, task_status_raw: str) -> Dict[str, Any]:
    # Backward-compatible wrapper: map old flat update API into new JSON store.
    params_dict = _parse_params_dict(params_dict_raw)
    task_updates = _parse_task_status(task_status_raw)
    store = _load_short_term_store()
    records = store.get("records", {})
    if not isinstance(records, dict):
        records = {}

    legacy = records.get("LEGACY", {})
    if not isinstance(legacy, dict):
        legacy = {}
    legacy["params"] = {str(k): v for k, v in params_dict.items()}
    legacy["tasks"] = {str(k): bool(v) for k, v in task_updates.items()}
    records["LEGACY"] = legacy

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    store["records"] = records
    store["last_update"] = ts
    _write_short_term_store(store)

    return {
        "ok": True,
        "action": "update_short_term",
        "file": str(SHORT_TERM_PATH),
        "updated_params": list(params_dict.keys()),
        "updated_tasks": list(task_updates.keys()),
        "last_update": ts,
    }


def cmd_cache_experience(experience_text: str) -> Dict[str, Any]:
    if not experience_text.strip():
        raise ValueError("--experience_text 不能为空")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = f"\n## {ts}\n{experience_text.strip()}\n"

    old = _load_markdown(TEMP_CACHE_PATH)
    TEMP_CACHE_PATH.write_text(old + block, encoding="utf-8")

    return {
        "ok": True,
        "action": "cache_experience",
        "file": str(TEMP_CACHE_PATH),
        "appended_chars": len(block),
    }


def _merge_long_term(cache_text: str) -> Tuple[bool, int]:
    if not cache_text.strip():
        return False, 0

    long_term_old = _load_markdown(LONG_TERM_PATH)
    if not long_term_old.endswith("\n"):
        long_term_old += "\n"

    merged_block = (
        f"\n## 合并于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{cache_text.strip()}\n"
    )
    LONG_TERM_PATH.write_text(long_term_old + merged_block, encoding="utf-8")
    TEMP_CACHE_PATH.write_text("", encoding="utf-8")
    return True, len(merged_block)


def cmd_commit_long_term() -> Dict[str, Any]:
    cache_text = _load_markdown(TEMP_CACHE_PATH)
    if not cache_text.strip():
        return {
            "ok": True,
            "action": "commit_long_term",
            "committed": False,
            "reason": "temp_experience_cache is empty",
            "cache_file": str(TEMP_CACHE_PATH),
        }

    print("\n===== 待合并经验缓存 =====")
    print(cache_text)
    print("===== 结束 =====\n")

    answer = input("【II级/III级权限确认】是否将以上经验正式合并到 memory/long_term_skills.md 中？(Y/N): ").strip().upper()

    if answer != "Y":
        return {
            "ok": True,
            "action": "commit_long_term",
            "committed": False,
            "reason": "user rejected merge",
            "cache_file": str(TEMP_CACHE_PATH),
            "long_term_file": str(LONG_TERM_PATH),
        }

    committed, merged_chars = _merge_long_term(cache_text)
    return {
        "ok": True,
        "action": "commit_long_term",
        "committed": committed,
        "merged_chars": merged_chars,
        "cache_file": str(TEMP_CACHE_PATH),
        "long_term_file": str(LONG_TERM_PATH),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Agent memory manager CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("reset_short_term", help="重置短期参数记忆为初始空白模板")

    p_save = subparsers.add_parser("save_short_term", help="保存/更新短期参数(JSON深度合并)")
    p_save.add_argument("--params_json", required=True, help="JSON object, e.g. {'Q1': {'cavity_freq_hz': {...}}}")

    p_get = subparsers.add_parser("get_short_term", help="读取短期参数，可按需求筛选")
    p_get.add_argument("--requirements_json", required=False, help="JSON object, e.g. {'Q1':['cavity_freq_hz'],'Q2':['pi_pulse']}")

    p_prepare = subparsers.add_parser("prepare_experiment_inputs", help="按需求提取短期参数并拼接接线图通道信息")
    p_prepare.add_argument("--requirements_json", required=True, help="JSON object, e.g. {'Q1':['cavity_freq_hz'],'Q2':['pi_pulse']}")

    p_update = subparsers.add_parser("update_short_term", help="更新短期上下文参数黑板和任务队列")
    p_update.add_argument("--params_dict", required=True, help="JSON string of parameter dict")
    p_update.add_argument("--task_status", required=True, help="Task status JSON/text")

    p_cache = subparsers.add_parser("cache_experience", help="缓存经验到临时文件")
    p_cache.add_argument("--experience_text", required=True, help="Experience text to append")

    subparsers.add_parser("commit_long_term", help="确认后合并缓存经验到长期库")

    args = parser.parse_args()

    try:
        _ensure_memory_files()

        if args.command == "reset_short_term":
            result = cmd_reset_short_term()
        elif args.command == "save_short_term":
            result = cmd_save_short_term(args.params_json)
        elif args.command == "get_short_term":
            result = cmd_get_short_term(args.requirements_json)
        elif args.command == "prepare_experiment_inputs":
            result = cmd_prepare_experiment_inputs(args.requirements_json)
        elif args.command == "update_short_term":
            result = cmd_update_short_term(args.params_dict, args.task_status)
        elif args.command == "cache_experience":
            result = cmd_cache_experience(args.experience_text)
        elif args.command == "commit_long_term":
            result = cmd_commit_long_term()
        else:
            raise ValueError(f"Unknown command: {args.command}")

        _print_json(result)

    except Exception as exc:
        _print_json(
            {
                "ok": False,
                "action": args.command,
                "error_type": exc.__class__.__name__,
                "message": str(exc),
            }
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
