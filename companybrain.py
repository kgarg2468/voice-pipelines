#!/usr/bin/env python3
"""companybrain — the client glue for the Company Brain demo.

Two pipelines do the smart work on the RocketRide engine; this script is the thin
client that (a) turns a capture run into markdown files on disk (the Obsidian vault)
and (b) asks the brain a question translated to a persona.

  python3 companybrain.py capture
      Run capture.pipe → the deep agent reads GitHub via tool_github and returns
      interlinked notes → we write them into ./vault/ (open that folder in Obsidian).

  python3 companybrain.py ask "what did Charlie ship?" --persona sales
      Read ./vault, hand the notes + question to brain.pipe, print the translated answer.

Connection defaults to the LOCAL engine (ws://localhost:5565, OSS key MYAPIKEY).
Secrets (ROCKETRIDE_OPENAI_KEY, etc.) load from ../.env. GitHub token comes from
ROCKETRIDE_GITHUB_TOKEN or `gh auth token`.
"""
import argparse, asyncio, json, os, re, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VAULT = HERE / "vault"
PRESENCE = VAULT / "presence"
CAPTURE_PIPE = HERE / "capture.pipe"
BRAIN_PIPE = HERE / "brain.pipe"
PLANNER_PIPE = HERE / "planner.pipe"
LOG_PIPE = HERE / "log.pipe"
DEFAULT_REPO = "kgarg2468/company-brain-demo"
PERSONAS = ("engineer", "sales")

# Map a file path to the feature it belongs to (matches the seeded src/ layout).
# Shared by presence logging and the Neo4j sync so the graph stays consistent.
FEATURE_RULES = [
    ("billing", "cloud-billing"),
    ("auth", "auth-refactor"),
    ("warm_pool", "warm-pool"),
    ("warmpool", "warm-pool"),
    ("health", "health"),
    ("observability", "observability"),
    ("trace", "observability"),
    ("tool_github", "tool-github"),
    ("vector_store", "vector-store"),
    ("scheduler", "pipeline-engine"),
    ("console", "web-console"),
    ("ratelimit", "rate-limiting"),
    ("/sdk/", "sdk-python"),
    ("docs/", "docs"),
]


def feature_of(path):
    """Best-effort file-path → feature slug (empty string if unknown)."""
    p = (path or "").lower()
    for key, slug in FEATURE_RULES:
        if key in p:
            return slug
    return ""


def load_env():
    """Load ../.env (and ./.env) into os.environ without requiring python-dotenv."""
    for env_path in (HERE.parent / ".env", HERE / ".env"):
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    # Default to the local engine unless the caller points elsewhere.
    if not os.environ.get("COMPANYBRAIN_URI") and not (os.environ.get("ROCKETRIDE_URI", "").startswith("ws")):
        os.environ["ROCKETRIDE_URI"] = "ws://localhost:5565"
        os.environ["ROCKETRIDE_APIKEY"] = os.environ.get("COMPANYBRAIN_AUTH") or "MYAPIKEY"


def gh_bin():
    """Return the GitHub CLI path or raise a stage-friendly setup error."""
    exe = os.environ.get("GH_BIN") or shutil.which("gh")
    if exe:
        return exe
    raise RuntimeError(
        "GitHub CLI `gh` was not found on PATH. Install it (`brew install gh`) "
        "and run `gh auth login`, or set GH_BIN=/path/to/gh."
    )


def _conn():
    uri = os.environ.get("COMPANYBRAIN_URI") or os.environ.get("ROCKETRIDE_URI") or "ws://localhost:5565"
    auth = os.environ.get("COMPANYBRAIN_AUTH") or os.environ.get("ROCKETRIDE_APIKEY") or "MYAPIKEY"
    return uri, auth


async def _run(pipe_path, message, timeout=180):
    """Start a pipeline, send one chat message, poll to completion, return answer text."""
    from rocketride import RocketRideClient
    from rocketride.schema import Question
    uri, auth = _conn()
    async with RocketRideClient(uri=uri, auth=auth) as c:
        # Start with tracing so the RocketRide IDE's Trace/Flow tabs light up for SDK/MCP runs.
        # Applies when this call STARTS the instance; reuse of an already-running instance keeps
        # its original level (restart the engine for a clean traced slate). Set COMPANYBRAIN_TRACE=none to disable.
        trace = os.environ.get("COMPANYBRAIN_TRACE", "full")
        started = await c.use(filepath=str(pipe_path), use_existing=True, pipelineTraceLevel=trace)
        token = started["token"] if isinstance(started, dict) else started
        q = Question(); q.addQuestion(message)
        resp = await c.chat(token=token, question=q)
        for _ in range(timeout):
            st = await c.get_task_status(token)
            state = st.get("state") if isinstance(st, dict) else st
            if state in (3, "completed", "failed", "terminated", None):
                break
            await asyncio.sleep(1)
    ans = resp.get("answers") if isinstance(resp, dict) else resp
    if isinstance(ans, list) and ans:
        return ans[0]
    return ans if isinstance(ans, str) else json.dumps(resp, default=str)


def _extract_json(text):
    """Pull the JSON object out of an agent answer (tolerates ``` fences / stray prose)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text).rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start:end + 1])
    raise ValueError("no JSON object found in capture answer")


# ---------------------------------------------------------------- capture
async def capture_async():
    # tool_github needs a token + repo, substituted client-side into the .pipe.
    if not os.environ.get("ROCKETRIDE_GITHUB_TOKEN"):
        tok = subprocess.run([gh_bin(), "auth", "token"], capture_output=True, text=True).stdout.strip()
        if tok:
            os.environ["ROCKETRIDE_GITHUB_TOKEN"] = tok
    os.environ.setdefault("ROCKETRIDE_GITHUB_REPO", DEFAULT_REPO)
    repo = os.environ["ROCKETRIDE_GITHUB_REPO"]
    print(f"[capture] reading {repo} via tool_github on the deep agent…", file=sys.stderr)
    answer = await _run(CAPTURE_PIPE, "Capture the latest activity from the repository into brain notes.")
    data = _extract_json(answer)
    notes = data.get("notes", [])
    VAULT.mkdir(exist_ok=True)
    written = []
    for note in notes:
        rel = note.get("path", "").lstrip("/")
        content = note.get("content", "")
        if not rel or not content:
            continue
        dest = VAULT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content if content.endswith("\n") else content + "\n")
        written.append(rel)
    print(f"[capture] {data.get('summary','captured')}")
    for w in sorted(written):
        print(f"   wrote vault/{w}")
    print(f"[capture] {len(written)} notes → {VAULT}  (open this folder in Obsidian)")
    return written


# ---------------------------------------------------------------- presence
def resolve_person(explicit=None):
    """Who is acting: explicit → COMPANYBRAIN_USER → git user.name → $USER → 'unknown'."""
    name = explicit or os.environ.get("COMPANYBRAIN_USER") or ""
    if not name:
        try:
            cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("COMPANYBRAIN_CWD") or str(HERE)
            name = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True,
                                  cwd=cwd).stdout.strip()
        except Exception:
            name = ""
    name = (name or os.environ.get("USER") or "unknown").strip().lower()
    return name.split()[0] if name else "unknown"


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def log_activity(person=None, working_on="", files=None, status="in_progress", max_files=12):
    """Upsert vault/presence/<person>.md with a rolling set of recently-touched files.
    Idempotent and safe to call on every edit (this is what the Claude Code hook calls)."""
    person = resolve_person(person)
    files = [f for f in (files or []) if f]
    PRESENCE.mkdir(parents=True, exist_ok=True)
    note = PRESENCE / f"{person}.md"
    seen, prev_working = [], ""
    if note.is_file():
        for line in note.read_text().splitlines():
            m = re.match(r"\s*-\s+`([^`]+)`", line)
            if m:
                seen.append(m.group(1))
            wm = re.match(r"working_on:\s*(.+)$", line)
            if wm:
                prev_working = wm.group(1).strip()
    merged = []
    for f in files + seen:               # newest first, de-duped, capped
        if f not in merged:
            merged.append(f)
    merged = merged[:max_files]
    working_on = working_on or prev_working
    feats = sorted({feature_of(f) for f in merged if feature_of(f)})
    lines = [
        "---", "type: presence", f"person: {person}", f"status: {status}",
        f"working_on: {working_on}", f"updated: {_now_iso()}", "---",
        f"**{person}** is currently working on {working_on or 'recent files'} (status: {status}).",
        "", "Recently touched files:",
    ]
    lines += [f"- `{f}`" for f in merged] or ["- (none yet)"]
    lines += ["", " ".join([f"[[people/{person}]]"] + [f"[[features/{s}]]" for s in feats])]
    note.write_text("\n".join(lines) + "\n")
    return note


def resolve_feature(issue=None, working_on="", files=None, repo=None):
    """Best-effort issue/work → feature slug. Deterministic client-side FALLBACK used
    only when log.pipe is unavailable. Order: working_on as text/path → working_on as a
    bare slug → files → the issue's 'feature:' label (read via gh) → issue title/body.
    Returns '' if nothing resolves. Never raises."""
    files = [f for f in (files or []) if f]
    wo = (working_on or "").strip()
    # working_on as descriptive text or a path (e.g. "billing meter", "src/health/probe.py")
    if wo and feature_of(wo):
        return feature_of(wo)
    # working_on already a bare slug (e.g. "warm-pool", "vector-store") that the rules don't catch
    if wo and " " not in wo and not wo.startswith("#") and not wo.startswith("src/"):
        return wo.lower()
    for f in files:                       # any touched file → its feature
        if feature_of(f):
            return feature_of(f)
    if issue is not None:                 # read the issue's feature: label from GitHub
        try:
            sys.path.insert(0, str(HERE))
            import sync_neo4j
            r = repo or os.environ.get("ROCKETRIDE_GITHUB_REPO") or DEFAULT_REPO
            item = sync_neo4j._gh_json(["issue", "view", str(issue), "--repo", r,
                                        "--json", "labels,title,body"])
            _, feats = sync_neo4j._labels(item)
            if feats:
                return feats[0]
            text = f"{item.get('title', '')} {item.get('body', '')}"
            if feature_of(text):
                return feature_of(text)
        except Exception:
            pass
    return ""


async def log_via_pipe(person=None, issue=None, working_on="", files=None, status="in_progress"):
    """Pipeline-first presence logging. Runs log.pipe — the deep agent reads GitHub and
    resolves the work into {feature, files} — then COMMITS that into the vault presence
    note + the Neo4j graph. The commit is client-side by necessity: the engine's db_neo4j
    is read-only and tool_filesystem can't reach the local vault. Falls back to the
    deterministic resolve_feature if the pipeline returns no usable slug, so the demo
    never stalls."""
    person = resolve_person(person)
    files = [f for f in (files or []) if f]
    # tool_github needs a token + repo, substituted client-side into the .pipe (as in capture).
    if not os.environ.get("ROCKETRIDE_GITHUB_TOKEN"):
        tok = subprocess.run([gh_bin(), "auth", "token"], capture_output=True, text=True).stdout.strip()
        if tok:
            os.environ["ROCKETRIDE_GITHUB_TOKEN"] = tok
    os.environ.setdefault("ROCKETRIDE_GITHUB_REPO", DEFAULT_REPO)

    task = f"issue #{issue}" if issue is not None else (working_on or "the work they described")
    read_hint = f"issue #{issue}" if issue is not None else "the repository"
    msg = (f"PERSON: {person}\n"
           f"TASK: {person} is picking up {task}.\n"
           f"Resolve which feature this work belongs to (and likely files) by reading {read_hint} "
           f"via the GitHub tool. Return the JSON object only.")
    print(f"[log] resolving {task} via log.pipe (deep agent + tool_github)…", file=sys.stderr)

    feature, pipe_files, via = "", [], "pipeline"
    try:
        answer = await _run(LOG_PIPE, msg)
        data = _extract_json(answer)
        feature = (data.get("feature") or "").strip().lower()
        pipe_files = [f for f in (data.get("files") or []) if f]
    except Exception as e:
        print(f"[log] pipeline returned no usable JSON ({e}); using deterministic resolver", file=sys.stderr)
        feature = ""

    # Anchor the conflict-critical slug to ground truth. The deep agent can grab the WRONG
    # issue (observed: it confabulated a billing issue for #11), so when we know the issue the
    # canonical 'feature:' label wins over the model. This is the demo-safety net.
    anchor = resolve_feature(issue=issue, working_on=working_on, files=files or pipe_files)
    if anchor:
        if feature and feature != anchor:
            print(f"[log] pipeline proposed '{feature}', issue label is '{anchor}' — anchoring to the label", file=sys.stderr)
            via = "pipeline (label-verified)"
        elif not feature:
            via = "fallback"
        feature = anchor
    elif not feature or feature.startswith("#") or " " in feature:
        feature = ""                     # nothing reliable; log_activity keeps any prior value
        via = "fallback"

    use_files = files or pipe_files
    if issue is not None and not use_files:    # enrich from the issue body (e.g. "new src/engine/health.py")
        try:
            sys.path.insert(0, str(HERE))
            import sync_neo4j
            r = os.environ.get("ROCKETRIDE_GITHUB_REPO") or DEFAULT_REPO
            it = sync_neo4j._gh_json(["issue", "view", str(issue), "--repo", r, "--json", "body"])
            use_files = re.findall(r"src/[\w./-]+\.py", it.get("body", ""))[:3]
        except Exception:
            pass
    note = log_activity(person=person, working_on=feature, files=use_files, status=status)

    synced, sync_error, counts = False, None, None
    try:
        sys.path.insert(0, str(HERE))
        import sync_neo4j
        counts = sync_neo4j.sync()
        synced = True
    except Exception as e:               # vault note is the source of truth; sync can re-run
        sync_error = str(e)

    return {"person": person, "feature": feature, "issue": issue, "note": str(note),
            "files": use_files, "via": via, "synced": synced, "sync_error": sync_error,
            "graph_counts": counts}


# ---------------------------------------------------------------- ask
def _read_vault():
    if not VAULT.is_dir():
        return ""
    chunks = []
    for md in sorted(VAULT.rglob("*.md")):
        chunks.append(f"### {md.relative_to(VAULT)}\n{md.read_text().strip()}")
    return "\n\n".join(chunks)


async def ask_async(question, persona):
    persona = persona if persona in PERSONAS else "engineer"
    notes = _read_vault()
    if not notes:
        return "The brain is empty — run `companybrain.py capture` first."
    message = f"PERSONA: {persona}\nQUESTION: {question}\n\nNOTES:\n{notes}"
    return await _run(BRAIN_PIPE, message)


# ---------------------------------------------------------------- plan (Neo4j)
async def plan_async(question):
    """Recommend a non-conflicting task. Syncs the live vault → Neo4j, reads a
    deterministic conflict summary, then lets the planner agent (which also has
    db_neo4j + tool_github) narrate a recommendation grounded in that summary."""
    sys.path.insert(0, str(HERE))
    summary = ""
    try:
        import sync_neo4j
        sync_neo4j.sync()
        summary = sync_neo4j.conflict_summary()
    except Exception as e:
        summary = f"(Neo4j graph unavailable — falling back to notes only: {e})"
    notes = _read_vault()
    message = (
        f"QUESTION: {question}\n\n"
        f"CONFLICT GRAPH SUMMARY (computed from Neo4j — who is on what, and which open "
        f"issues are in untouched areas):\n{summary}\n\n"
        f"BRAIN NOTES (issues, PRs, live presence):\n{notes}"
    )
    return await _run(PLANNER_PIPE, message)


# ---------------------------------------------------------------- prime (IDE tracing)
async def prime_async():
    """(Re)start every pipeline as a TRACED instance so the RocketRide IDE's Trace/Flow tabs
    show per-node steps for later Claude Code / CLI runs. A task's trace level is fixed when it
    STARTS, and runs reuse a running instance (use_existing) — so an instance started untraced
    (e.g. days ago) stays untraced forever. We terminate whatever's running and start a fresh
    instance with pipelineTraceLevel=full. Run once before a demo (idempotent)."""
    from rocketride import RocketRideClient
    # tool_github pipes (capture, log) need a token + repo substituted client-side (as in capture).
    if not os.environ.get("ROCKETRIDE_GITHUB_TOKEN"):
        tok = subprocess.run([gh_bin(), "auth", "token"], capture_output=True, text=True).stdout.strip()
        if tok:
            os.environ["ROCKETRIDE_GITHUB_TOKEN"] = tok
    os.environ.setdefault("ROCKETRIDE_GITHUB_REPO", DEFAULT_REPO)
    uri, auth = _conn()
    pipes = [CAPTURE_PIPE, BRAIN_PIPE, PLANNER_PIPE, LOG_PIPE]
    async with RocketRideClient(uri=uri, auth=auth) as c:
        for pipe in pipes:
            name = pipe.stem
            try:                                  # clear whatever's running (likely untraced)
                started = await c.use(filepath=str(pipe), use_existing=True)
                tok = started["token"] if isinstance(started, dict) else started
                await c.terminate(tok)
                await asyncio.sleep(2)
            except Exception as e:
                print(f"[prime] {name}: nothing to clear ({e})", file=sys.stderr)
            for attempt in range(3):              # start a FRESH traced idle instance (no timeout)
                try:
                    started = await c.use(filepath=str(pipe), pipelineTraceLevel="full", ttl=0)
                    tok = started["token"] if isinstance(started, dict) else started
                    print(f"[prime] {name}: traced instance ready ({str(tok)[:14]})")
                    break
                except Exception as e:
                    if "already running" in str(e).lower() and attempt < 2:
                        await asyncio.sleep(2)
                        continue
                    print(f"[prime] {name}: FAILED to start traced ({e})", file=sys.stderr)
                    break
    print("[prime] done — open a .pipe in the RocketRide IDE (Trace tab); runs now stream per-node steps.")


# ---------------------------------------------------------------- CLI
def main():
    load_env()
    ap = argparse.ArgumentParser(description="Company Brain client")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("capture", help="read GitHub → write the vault")
    pa = sub.add_parser("ask", help="ask the brain, translated to a persona")
    pa.add_argument("question")
    pa.add_argument("--persona", "-p", default="engineer", choices=PERSONAS)
    pl = sub.add_parser("log-activity", help="record what a person is working on (used by the hook)")
    pl.add_argument("--person", default=None)
    pl.add_argument("--working-on", dest="working_on", default="")
    pl.add_argument("--files", nargs="*", default=[])
    pl.add_argument("--status", default="in_progress")
    pp = sub.add_parser("plan", help="recommend a task that won't conflict (uses the Neo4j graph)")
    pp.add_argument("question")
    li = sub.add_parser("log-issue", help="resolve+log a task THROUGH log.pipe, then update vault + Neo4j")
    li.add_argument("--person", default=None)
    li.add_argument("--issue", type=int, default=None)
    li.add_argument("--working-on", dest="working_on", default="")
    li.add_argument("--files", nargs="*", default=[])
    li.add_argument("--status", default="in_progress")
    sub.add_parser("build-vault", help="deterministically rebuild the vault + Neo4j graph from GitHub + presence")
    sub.add_parser("prime", help="(re)start all pipelines as TRACED instances so the IDE Trace/Flow tabs show steps")
    args = ap.parse_args()
    if args.cmd == "capture":
        asyncio.run(capture_async())
    elif args.cmd == "ask":
        print(asyncio.run(ask_async(args.question, args.persona)))
    elif args.cmd == "log-activity":
        note = log_activity(args.person, args.working_on, args.files, args.status)
        print(f"[presence] {resolve_person(args.person)} → {note}")
    elif args.cmd == "plan":
        print(asyncio.run(plan_async(args.question)))
    elif args.cmd == "log-issue":
        res = asyncio.run(log_via_pipe(args.person, args.issue, args.working_on, args.files, args.status))
        print(f"[log-issue] {res['person']} → {res['feature'] or '(unresolved)'} "
              f"(issue {res['issue']}, via {res['via']})")
        print(f"[log-issue] note {res['note']}")
        if res["synced"]:
            print(f"[log-issue] Neo4j updated: {res['graph_counts']}")
        else:
            print(f"[log-issue] Neo4j sync skipped/failed: {res['sync_error']}")
    elif args.cmd == "build-vault":
        sys.path.insert(0, str(HERE))
        import sync_neo4j
        g, v = sync_neo4j.sync(), sync_neo4j.build_vault()
        print(f"[build-vault] graph nodes {g}\n[build-vault] vault notes {v}\n")
        print(sync_neo4j.conflict_summary())
    elif args.cmd == "prime":
        asyncio.run(prime_async())


if __name__ == "__main__":
    main()
