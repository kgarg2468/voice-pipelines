#!/usr/bin/env python3
"""companybrain_mcp — a tiny, dependency-free MCP stdio server so Claude Code can
pull from the Company Brain.

Exposes ONE tool:
    ask_company_brain(question, persona)  → the brain's answer, translated to the persona.

It reads the local Obsidian vault and routes the question through brain.pipe on the
RocketRide engine (see companybrain.py). Implements just enough of the MCP stdio
protocol (newline-delimited JSON-RPC 2.0) to register with `claude mcp add` — no
`mcp` package required.

Register (from this folder):
    claude mcp add company-brain -- python3 "$(pwd)/companybrain_mcp.py"
Then in Claude Code:  "ask the company brain, as sales, what Charlie shipped"
"""
import asyncio, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import companybrain as cb

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "company-brain", "version": "1.0.0"}
TOOL = {
    "name": "ask_company_brain",
    "description": (
        "Answer a question from the company brain (GitHub activity captured as an "
        "interlinked note vault), TRANSLATED to the asker's role. Use this to find out "
        "what teammates shipped, the status of work, who owns what, and what it means — "
        "without pinging anyone."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "What you want to know."},
            "persona": {
                "type": "string",
                "enum": list(cb.PERSONAS),
                "default": "engineer",
                "description": "Translate the answer for this role: 'engineer' (technical) or 'sales' (customer-facing).",
            },
        },
        "required": ["question"],
    },
}

PLAN_TOOL = {
    "name": "plan_task",
    "description": (
        "Recommend a task to pick up that WON'T conflict with anyone. Reads the team's "
        "Neo4j conflict graph (who is actively working which feature, via open PRs + live "
        "edits) and returns a safe, unassigned open issue plus what to avoid and who to "
        "coordinate with. Use when someone asks for the pressing release issues or what to work on."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "default": "What pressing release issue can I pick up that won't conflict with anyone?",
                "description": "What you want planned (optional; a sensible default is used).",
            },
        },
    },
}

LOG_TOOL = {
    "name": "log_activity",
    "description": (
        "Record that the current user has started working on something, so the Company "
        "Brain reflects it immediately. Runs the log pipeline (a deep agent that reads GitHub "
        "to resolve the issue → feature), then updates the Obsidian presence note AND the Neo4j "
        "conflict graph — so the next person's plan_task routes around this work. Call this right "
        "after the user says they're picking up an issue (e.g. 'ok I'm on #11', 'log that I'm "
        "working on the healthz probe'). Pass the issue number when known."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "issue": {
                "type": "integer",
                "description": "GitHub issue number being picked up (e.g. 11). Used to resolve the feature it belongs to.",
            },
            "working_on": {
                "type": "string",
                "default": "",
                "description": "Optional explicit feature slug or focus (e.g. 'health'). Usually leave empty and let 'issue' resolve it.",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "Optional file paths the user will touch (e.g. ['src/health/probe.py']). Improves graph accuracy.",
            },
            "person": {
                "type": "string",
                "description": "Who is working. Optional — defaults to COMPANYBRAIN_USER, then git user.name, then $USER.",
            },
            "status": {
                "type": "string",
                "default": "in_progress",
                "description": "Work status to record (e.g. 'in_progress', 'done').",
            },
        },
    },
}

TOOLS = [TOOL, PLAN_TOOL, LOG_TOOL]


def _send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _result(rid, result):
    _send({"jsonrpc": "2.0", "id": rid, "result": result})


def _error(rid, code, message):
    _send({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


def _handle(req):
    method = req.get("method")
    rid = req.get("id")
    is_notification = "id" not in req

    if method == "initialize":
        client_pv = (req.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        _result(rid, {
            "protocolVersion": client_pv,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
    elif method == "notifications/initialized" or (is_notification and method and method.startswith("notifications/")):
        pass  # notifications get no response
    elif method == "ping":
        _result(rid, {})
    elif method == "tools/list":
        _result(rid, {"tools": TOOLS})
    elif method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "ask_company_brain":
                answer = asyncio.run(cb.ask_async(args.get("question", ""), args.get("persona", "engineer")))
            elif name == "plan_task":
                q = args.get("question") or "What pressing release issue can I pick up that won't conflict with anyone?"
                answer = asyncio.run(cb.plan_async(q))
            elif name == "log_activity":
                raw_issue = args.get("issue")
                try:
                    issue = int(raw_issue) if raw_issue not in (None, "") else None
                except (TypeError, ValueError):
                    issue = None  # tolerate "#11"/junk; the resolver falls back to working_on/files
                res = asyncio.run(cb.log_via_pipe(
                    person=args.get("person"),
                    issue=issue,
                    working_on=args.get("working_on", ""),
                    files=args.get("files") or [],
                    status=args.get("status", "in_progress"),
                ))
                feat = res.get("feature") or "(unresolved feature)"
                who, via = res.get("person"), res.get("via")
                iss = f" (issue #{res['issue']})" if res.get("issue") else ""
                if res.get("synced"):
                    g = res.get("graph_counts") or {}
                    answer = (f"Logged via {via}: {who} → {feat}{iss}. Presence note updated and Neo4j "
                              f"rebuilt ({g.get('Person', '?')} people / {g.get('Feature', '?')} features). "
                              f"The conflict graph now shows {who} on {feat}; the next plan_task will route around it.")
                else:
                    answer = (f"Logged via {via}: {who} → {feat}{iss}. Presence note updated. "
                              f"Neo4j sync was skipped/failed ({res.get('sync_error')}); "
                              f"run `python3 sync_neo4j.py` to refresh the graph.")
            else:
                _error(rid, -32602, f"unknown tool: {name}")
                return
            _result(rid, {"content": [{"type": "text", "text": str(answer)}], "isError": False})
        except Exception as e:  # surface errors as tool output, not a transport crash
            _result(rid, {"content": [{"type": "text", "text": f"company-brain error: {e}"}], "isError": True})
    elif is_notification:
        pass
    else:
        _error(rid, -32601, f"method not found: {method}")


def main():
    cb.load_env()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            _handle(req)
        except Exception as e:
            print(f"[company-brain] handler error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
