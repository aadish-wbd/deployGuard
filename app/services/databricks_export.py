"""Parse Databricks jobs/runs/export responses into notebook models and failure context."""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

from app.core.limits import MAX_LOG_SNIPPET_CHARS, MAX_NOTEBOOK_CONTEXT_CHARS, MAX_STACK_TRACE_CHARS


def _decode_model_payload(payload: str) -> dict:
    """Decode URL-encoded JSON, including base64-wrapped exports from jobs/runs/export."""
    candidates = [payload]
    try:
        candidates.append(base64.b64decode(payload).decode("utf-8"))
    except Exception:
        pass

    for candidate in candidates:
        for decoded in (candidate, unquote(candidate)):
            try:
                return json.loads(decoded)
            except json.JSONDecodeError:
                continue

    raise ValueError("Could not decode __DATABRICKS_NOTEBOOK_MODEL payload")


def extract_notebook_model(html: str) -> dict:
    match = re.search(
        r"var __DATABRICKS_NOTEBOOK_MODEL = '([^']+)'",
        html,
    )
    if not match:
        raise ValueError("Could not find __DATABRICKS_NOTEBOOK_MODEL in export HTML")
    return _decode_model_payload(match.group(1))


def export_html(export_data: dict) -> str:
    views = export_data.get("views") or []
    if not views:
        raise ValueError("Databricks export response has no views")
    content = views[0].get("content")
    if not isinstance(content, str):
        raise ValueError("Databricks export view content is missing or not a string")
    return content


def _parse_error_summary(summary: str) -> Tuple[str, str]:
    if not summary:
        return "Error", ""
    if ": " in summary:
        ename, evalue = summary.split(": ", 1)
        return ename.strip(), evalue.strip()
    return "Error", summary.strip()


def _stream_output(stream_name: str, text: str) -> dict:
    lines = text.splitlines(keepends=True)
    if text and not text.endswith("\n"):
        lines.append("\n")
    return {"output_type": "stream", "name": stream_name, "text": lines or [""]}


def _error_output(summary: str, traceback_text: Optional[str]) -> dict:
    ename, evalue = _parse_error_summary(summary)
    if traceback_text:
        traceback = traceback_text.splitlines(keepends=True)
        if traceback and not traceback[-1].endswith("\n"):
            traceback[-1] += "\n"
    else:
        traceback = [f"{ename}: {evalue}\n"] if evalue else [f"{ename}\n"]
    return {
        "output_type": "error",
        "ename": ename,
        "evalue": evalue,
        "traceback": traceback,
    }


def _results_to_outputs(cmd: dict) -> List[dict]:
    outputs: List[dict] = []
    results = cmd.get("results")
    if isinstance(results, dict):
        for item in results.get("data") or []:
            item_type = item.get("type")
            text = item.get("data")
            if item_type == "ansi" and isinstance(text, str):
                stream_name = item.get("name") or "stdout"
                if stream_name not in ("stdout", "stderr"):
                    stream_name = "stdout"
                outputs.append(_stream_output(stream_name, text))
            elif item_type == "html" and isinstance(text, str):
                outputs.append(
                    {
                        "output_type": "display_data",
                        "data": {"text/html": text},
                        "metadata": {},
                    }
                )
            elif item_type == "table" and item.get("data") is not None:
                outputs.append(
                    {
                        "output_type": "display_data",
                        "data": {"text/plain": str(item.get("data"))},
                        "metadata": {},
                    }
                )

    summary = cmd.get("errorSummary") or ""
    error_text = cmd.get("error")
    state = cmd.get("state")

    if error_text:
        outputs.append(_error_output(summary, error_text))
    elif state == "error" and summary and summary != "Command skipped":
        outputs.append(_error_output(summary, None))
    elif state == "error" and summary == "Command skipped":
        outputs.append(_stream_output("stderr", "Command skipped\n"))

    return outputs


def command_to_cell(cmd: dict) -> dict:
    source = cmd.get("command", "")
    if isinstance(source, str):
        lines = source.splitlines(keepends=True)
        if lines and not lines[-1].endswith("\n"):
            lines[-1] = lines[-1] + "\n"
    else:
        lines = [""]

    title = cmd.get("commandTitle", "")
    metadata: Dict[str, Any] = {}
    if title:
        metadata["application/vnd.databricks.v1+cell"] = {"title": title}

    if isinstance(source, str) and source.lstrip().startswith("%md"):
        md = source.lstrip()
        if md.startswith("%md"):
            md = md[3:].lstrip("\n\r ")
        md_lines = md.splitlines(keepends=True)
        if md_lines and not md_lines[-1].endswith("\n"):
            md_lines[-1] = md_lines[-1] + "\n"
        return {
            "cell_type": "markdown",
            "metadata": metadata,
            "source": md_lines if md_lines else [""],
        }

    outputs = _results_to_outputs(cmd)
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": metadata,
        "outputs": outputs,
        "source": lines if lines else [""],
    }


def to_ipynb(model: dict) -> dict:
    commands = sorted(model.get("commands", []), key=lambda c: c.get("position", 0))
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": model.get("language", "python"),
                "name": "python3",
            },
            "language_info": {"name": model.get("language", "python")},
            "application/vnd.databricks.v1+notebook": {
                "notebookName": model.get("name", "exported_notebook"),
                "originalId": model.get("origId"),
            },
        },
        "cells": [command_to_cell(cmd) for cmd in commands],
    }


def _is_markdown_command(source: str) -> bool:
    return isinstance(source, str) and source.lstrip().startswith("%md")


def _format_cell_block(cell_num: int, cmd: dict, *, is_failed: bool) -> str:
    source = cmd.get("command") or ""
    title = (cmd.get("commandTitle") or "").strip()
    cell_type = "markdown" if _is_markdown_command(source) else "code"

    header = f"--- cell {cell_num} ({cell_type})"
    if title:
        header += f": {title}"
    if is_failed:
        header += " [FAILED]"

    lines = [header]
    if cell_type == "markdown":
        md = source.lstrip()
        if md.startswith("%md"):
            md = md[3:].lstrip("\n\r ")
        if md:
            lines.extend(md.splitlines())
    else:
        src_lines = source.splitlines() if isinstance(source, str) else []
        width = max(len(str(len(src_lines))), 1) if src_lines else 1
        for line_no, line in enumerate(src_lines, 1):
            lines.append(f"{line_no:>{width}}| {line}")

    if is_failed:
        summary = (cmd.get("errorSummary") or "").strip()
        error_text = (cmd.get("error") or "").strip()
        if summary:
            lines.append(f"error: {summary}")
        if error_text and error_text != summary:
            lines.append("traceback:")
            lines.extend(error_text.splitlines())

    return "\n".join(lines)


def _truncate_cell_source(block: str, max_chars: int) -> str:
    """Shrink a cell block by trimming middle source lines, keeping header and error tail."""
    if len(block) <= max_chars:
        return block

    lines = block.splitlines()
    if not lines:
        return _truncate(block, max_chars)

    header = lines[0]
    tail: List[str] = []
    for i in range(len(lines) - 1, 0, -1):
        tail.insert(0, lines[i])
        if lines[i].startswith("error:") or lines[i] == "traceback:":
            break
    if not any(line.startswith("error:") for line in tail):
        tail = lines[-min(5, len(lines) - 1) :]

    body_lines = lines[1 : len(lines) - len(tail)]
    kept: List[str] = [header]
    omitted = False
    for line in body_lines:
        candidate = "\n".join(kept + [line] + ([""] if tail else []) + tail)
        if len(candidate) > max_chars - 20:
            omitted = True
            break
        kept.append(line)

    if omitted:
        kept.append("... source truncated ...")
    kept.extend(tail)
    return _truncate("\n".join(kept), max_chars)


def format_notebook_for_agent(model: dict, failed: dict) -> str:
    """Render only the failed notebook cell with line numbers for the Bedrock agent."""
    commands = sorted(model.get("commands", []), key=lambda c: c.get("position", 0))
    failed_position = failed.get("position", 0)
    cell_num = sum(1 for cmd in commands if cmd.get("position", 0) <= failed_position)

    header = f"notebook: {model.get('name', 'exported_notebook')}"
    budget = MAX_NOTEBOOK_CONTEXT_CHARS - len(header) - 1

    failed_block = _format_cell_block(cell_num, failed, is_failed=True)
    if len(failed_block) > budget:
        failed_block = _truncate_cell_source(failed_block, budget)

    return _truncate(f"{header}\n{failed_block}", MAX_NOTEBOOK_CONTEXT_CHARS)


def _collect_stderr_lines(cmd: dict) -> List[str]:
    lines: List[str] = []
    results = cmd.get("results")
    if not isinstance(results, dict):
        return lines
    for item in results.get("data") or []:
        if item.get("type") == "ansi" and item.get("name") == "stderr":
            text = item.get("data")
            if isinstance(text, str):
                lines.extend(text.splitlines())
    return lines


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def extract_failure_context(export_data: dict) -> dict:
    """Extract error_message, stack_trace, and log_snippet from a run export."""
    html = export_html(export_data)
    model = extract_notebook_model(html)
    commands = sorted(model.get("commands", []), key=lambda c: c.get("position", 0))

    failed: Optional[dict] = None
    for cmd in reversed(commands):
        if cmd.get("state") == "error" and cmd.get("errorSummary") != "Command skipped":
            failed = cmd
            break

    if failed is None:
        for cmd in reversed(commands):
            if cmd.get("state") == "error":
                failed = cmd
                break

    if failed is None:
        raise ValueError("No failed command found in Databricks run export")

    error_summary = (failed.get("errorSummary") or "").strip()
    error_text = (failed.get("error") or "").strip()
    task_name = failed.get("commandTitle") or None

    error_message = error_summary or error_text.splitlines()[0] if error_text else "Databricks job failed"
    error_message = _truncate(error_message, 500)

    stack_trace = error_text or error_summary
    stack_trace = _truncate(stack_trace, MAX_STACK_TRACE_CHARS) if stack_trace else None

    log_lines: List[str] = []
    failed_position = failed.get("position", 0)
    for cmd in commands:
        if cmd.get("position", 0) > failed_position:
            continue
        log_lines.extend(_collect_stderr_lines(cmd))

    if not log_lines and error_text:
        log_lines = error_text.splitlines()

    log_snippet = _truncate("\n".join(log_lines[-20:]), MAX_LOG_SNIPPET_CHARS) if log_lines else None
    notebook_context = format_notebook_for_agent(model, failed)

    return {
        "error_message": error_message,
        "stack_trace": stack_trace,
        "log_snippet": log_snippet,
        "task_name": task_name,
        "notebook_name": model.get("name"),
        "notebook_context": notebook_context,
    }
