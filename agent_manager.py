from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

MEMORY_DIR = Path("memory")
SHORT_TERM_PATH = MEMORY_DIR / "short_term_context.md"
TEMP_CACHE_PATH = MEMORY_DIR / "temp_experience_cache.md"
LONG_TERM_PATH = MEMORY_DIR / "long_term_skills.md"

SHORT_TERM_TEMPLATE = """# 短期上下文\n\n## 任务队列\n- [ ] 初始化任务队列\n\n## 参数黑板\n- last_update: N/A\n\n## 文件指针\n- latest_db: N/A\n- latest_plot: N/A\n"""


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _ensure_memory_files() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

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


def _parse_existing_task_lines(body: str) -> Dict[str, bool]:
    tasks: Dict[str, bool] = {}
    for line in body.splitlines():
        m = re.match(r"^-\s*\[( |x|X)\]\s*(.+)$", line.strip())
        if m:
            tasks[m.group(2).strip()] = m.group(1).lower() == "x"
    return tasks


def _parse_existing_param_lines(body: str) -> Dict[str, str]:
    params: Dict[str, str] = {}
    for line in body.splitlines():
        m = re.match(r"^-\s*([^:]+):\s*(.+)$", line.strip())
        if m:
            params[m.group(1).strip()] = m.group(2).strip()
    return params


def cmd_update_short_term(params_dict_raw: str, task_status_raw: str) -> Dict[str, Any]:
    params_dict = _parse_params_dict(params_dict_raw)
    task_updates = _parse_task_status(task_status_raw)

    md = _load_markdown(SHORT_TERM_PATH)
    for section in ("任务队列", "参数黑板", "文件指针"):
        md = _ensure_section(md, section)

    task_pat = re.compile(r"(^##\s+任务队列\s*$)(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
    param_pat = re.compile(r"(^##\s+参数黑板\s*$)(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)

    task_match = task_pat.search(md)
    param_match = param_pat.search(md)
    if task_match is None or param_match is None:
        raise RuntimeError("短期上下文模板异常，缺少必要区块")

    existing_tasks = _parse_existing_task_lines(task_match.group(2))
    existing_tasks.update(task_updates)

    existing_params = _parse_existing_param_lines(param_match.group(2))
    for k, v in params_dict.items():
        existing_params[str(k)] = str(v)
    existing_params["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    task_body_lines = [f"- [{'x' if done else ' '}] {task}" for task, done in existing_tasks.items()]
    param_body_lines = [f"- {k}: {v}" for k, v in existing_params.items()]

    md = _replace_section_body(md, "任务队列", "\n".join(task_body_lines))
    md = _replace_section_body(md, "参数黑板", "\n".join(param_body_lines))

    SHORT_TERM_PATH.write_text(md, encoding="utf-8")

    return {
        "ok": True,
        "action": "update_short_term",
        "file": str(SHORT_TERM_PATH),
        "updated_params": list(params_dict.keys()),
        "updated_tasks": list(task_updates.keys()),
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

    p_update = subparsers.add_parser("update_short_term", help="更新短期上下文参数黑板和任务队列")
    p_update.add_argument("--params_dict", required=True, help="JSON string of parameter dict")
    p_update.add_argument("--task_status", required=True, help="Task status JSON/text")

    p_cache = subparsers.add_parser("cache_experience", help="缓存经验到临时文件")
    p_cache.add_argument("--experience_text", required=True, help="Experience text to append")

    subparsers.add_parser("commit_long_term", help="确认后合并缓存经验到长期库")

    args = parser.parse_args()

    try:
        _ensure_memory_files()

        if args.command == "update_short_term":
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
