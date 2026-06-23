#!/usr/bin/env python3
"""watch_pipelines — a live trace console for the Company Brain demo.

Run this in a SIDE TERMINAL during the demo. It subscribes to the local RocketRide
engine's event stream (token='*') and prints, in real time, which pipeline is running
and which NODES are executing — visible proof that capture/brain/planner/log actually
run on the engine when you ask in Claude Code.

    python3 watch_pipelines.py

What you'll see while a question is answered:
    ▶  planner — run active
       ● nodes: deep agent + Neo4j tool
       🧠 deep agent reasoning…
    ■  planner — idle

Signals used (verified on this OSS engine build): apaevt_sse 'thinking' (agent
reasoning) and apaevt_status_update.pipeflow (the live active-component stack). FLOW
traces aren't emitted by this build, so we render the node stack instead.
"""
import asyncio, json, sys, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import companybrain as cb
from rocketride import RocketRideClient

# Friendly labels for the node ids used across the four pipelines.
NODE = {
    "chat_1": "chat (input)", "agent_1": "deep agent", "llm_1": "OpenAI LLM",
    "tool_github_1": "GitHub tool", "db_neo4j_1": "Neo4j tool", "response_1": "answer (output)",
}

# Map each pipeline's project_id → its filename stem (capture / brain / planner / log).
PID2NAME = {}
for p in sorted(HERE.glob("*.pipe")):
    try:
        PID2NAME[json.load(open(p)).get("project_id")] = p.stem
    except Exception:
        pass


def labels(ids):
    return " + ".join(NODE.get(i, i) for i in ids)


def pname(pid):
    return PID2NAME.get(pid) or (pid[:8] if pid else "?")


def ts():
    return datetime.now().strftime("%H:%M:%S")


# Per-pipeline last-seen active node set, so each event is attributed by its OWN
# project_id (all 4 pipelines stay warm and emit idle status — don't let them cross-talk).
_last = {}        # pipeline name -> last active node tuple
_sse_t = [0.0]    # throttle for the "reasoning…" heartbeat


async def on_event(ev):
    et = ev.get("event")
    body = ev.get("body") or {}

    if et == "apaevt_status_update":
        name = pname(body.get("project_id"))
        pf = (body.get("pipeflow") or {}).get("byPipe") or {}
        active = tuple(i for stack in pf.values() for i in stack)
        prev = _last.get(name, ())
        if active and active != prev:               # this pipeline just lit up (new node set)
            if not prev:
                print(f"{ts()} ▶  {name} — run active")
            print(f"{ts()}    ● {name}: {labels(active)}")
        elif not active and prev:                   # this pipeline went idle → run finished
            toks = (body.get("tokens") or {}).get("total")
            print(f"{ts()} ■  {name} — done{f'  (tokens: {toks})' if toks else ''}\n")
        _last[name] = active

    elif et == "apaevt_sse" and body.get("type") == "thinking":
        now = time.monotonic()                      # throttle: agents emit many 'thinking' SSEs
        if now - _sse_t[0] > 1.5:
            print(f"{ts()}    🧠 deep agent reasoning…")
            _sse_t[0] = now


async def main():
    cb.load_env()
    try:
        sys.stdout.reconfigure(line_buffering=True)   # flush each line (so piping to a log works live)
    except Exception:
        pass
    uri, auth = cb._conn()
    print(f"watching engine {uri}")
    print("pipelines:", ", ".join(sorted(set(PID2NAME.values()))) or "(none found)")
    print("→ ask something in Claude Code (or run a CLI command). Ctrl-C to stop.\n")
    client = RocketRideClient(uri=uri, auth=auth, on_event=on_event)
    await client.connect()
    await client.set_events("*", ["TASK", "SUMMARY", "FLOW", "OUTPUT", "SSE"])
    try:
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[watch] stopped.")
