#!/usr/bin/env python3
"""report_activity — a Claude Code PostToolUse hook that feeds the Company Brain.

Wire it into ~/.claude/settings.json so that whenever a session edits/reads a file,
the brain learns "<person> is touching <file>". It is INERT unless COMPANYBRAIN_USER
is set in the session's environment — so it does nothing in normal work, and in a demo
you make two "people" on one laptop by exporting COMPANYBRAIN_USER=charlie (resp. dana)
before launching `claude` in each terminal.

settings.json:
  "hooks": { "PostToolUse": [ { "matcher": "Read|Write|Edit",
    "hooks": [ { "type": "command", "command": "python3 /ABS/PATH/hooks/report_activity.py", "async": true } ] } ] }

Contract: read the hook JSON on stdin, never raise, always print {} and exit 0 so it
can never disrupt the session.
"""
import json, os, sys
from pathlib import Path


def main():
    raw = sys.stdin.read()
    # Inert unless a demo identity is set — keeps the global hook harmless.
    person = os.environ.get("COMPANYBRAIN_USER")
    if not person:
        return
    try:
        data = json.loads(raw or "{}")
    except Exception:
        return
    tool_input = data.get("tool_input") or {}
    fp = tool_input.get("file_path")
    if not fp:
        return  # not a file-touching tool call
    cwd = data.get("cwd") or os.getcwd()
    try:
        rel = os.path.relpath(fp, cwd)
        if rel.startswith(".."):     # outside the project — keep a readable tail
            rel = os.path.join(*Path(fp).parts[-3:])
    except Exception:
        rel = fp

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import companybrain as cb
    cb.load_env()
    cb.log_activity(person=person, files=[rel], working_on=cb.feature_of(rel))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[company-brain hook] {e}", file=sys.stderr)
    finally:
        # MCP/Claude expect a JSON object on stdout; empty = pass-through.
        print("{}")
        sys.exit(0)
