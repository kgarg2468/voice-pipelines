# Company Brain — stage runbook

## Pre-flight (before you walk on)
- [ ] **Local engine up:** `nc -z localhost 5565` succeeds. (Engine: RocketRide app → Local mode.)
- [ ] **Keys + GitHub CLI:** `.env` has `ROCKETRIDE_OPENAI_KEY`; `gh auth status` is logged in (install with `brew install gh`, or set `GH_BIN=/path/to/gh`).
- [ ] **Repo seeded:** `gh repo view kgarg2468/company-brain-demo` exists. If not: `./seed_repo.sh`.
- [ ] **Baseline brain:** `python3 companybrain.py build-vault` ran → `vault/` has ~55 notes + the Neo4j graph (≈60 nodes). (`capture` is the live agent beat; `build-vault` is the deterministic dense build.)
- [ ] **Obsidian:** open the `vault/` folder as a vault; open **Graph view**; leave it on the projector.
- [ ] **Claude Code wired:** `claude mcp list` shows `company-brain … ✔ Connected`. **Start a FRESH
      `claude` session** (the `log_activity` tool only loads on a new session) and confirm 3 tools.
- [ ] **Log as the right person:** in the Claude Code terminal you demo in, `export COMPANYBRAIN_USER=krish`
      **before** launching `claude` — otherwise "log that I'm on #11" records your git username, not `krish`.
- [ ] **Prime tracing (for the IDE Trace/Flow tabs):** `python3 companybrain.py prime` — (re)starts all four
      pipelines as **traced** instances so the IDE shows each node step on every run. Run once, after the engine is up.
- [ ] **Dry-run the ask** once: `python3 companybrain.py ask "what did Charlie ship?" -p sales`.

## Seeing the pipelines run (proof on screen)
Two options — use either or both:

**A. In the RocketRide IDE (Trace / Flow / Status / Tokens tabs) — primary.** Requires the pre-flight
`python3 companybrain.py prime` (it (re)starts every pipeline as a **traced** instance — without it the
Trace tab stays "No trace data" because runs reuse an older untraced instance). The IDE monitors only the
`.pipe` file **currently open**, matched by its `project_id`. So:
- **Open the SAME pipeline you're about to run** — `brain.pipe` for the sales ask; `planner.pipe` then
  `log.pipe` for the engineer act. (Common mistake: watching `brain.pipe` while running plan/log → the IDE
  shows nothing because those are different pipelines.)
- Ask in Claude Code → the **Trace** tab fills with each node step (Chat → Deep Agent → …); **Flow** shows
  nodes light up, **Status/Tokens** show live state + cost.
- If Trace is still empty after `prime`: the local engine is likely a stale/orphaned process. Truly restart
  it — `lsof -iTCP:5565 -sTCP:LISTEN` → `kill <pid>` → relaunch via the RocketRide app (Local mode) — then
  re-run `prime`. (Disable tracing entirely with `COMPANYBRAIN_TRACE=none`.)

**B. Side-terminal trace console (most reliable):** `python3 watch_pipelines.py`. Prints each run live —
`▶ planner — run active / ● deep agent + OpenAI LLM / 🧠 reasoning… / ■ done (tokens: …)`. Works for every
run regardless of which file is open in the IDE.

## The 90-second script
1. **Frame it (10s).** "Everyone wastes time syncing, and translating between an engineer and a
   salesperson. Here's a brain that does both." Show the Obsidian graph — *"this is our company,
   captured from GitHub: people, PRs, features, issues, all wired together."*
2. **Make news (15s).** `./make_news.sh` → "Charlie just merged a PR — streaming trace events."
3. **Capture live (15s).** `python3 companybrain.py capture` → a **new node pops into the graph**,
   linked to `[[people/charlie]]` and `[[features/observability]]`. *"No one told the brain. It saw it."*
4. **Translate (30s).** In Claude Code: *"ask the company brain, as sales, what did Charlie just ship
   and what does it mean for customers?"* → read the sales answer. Then: *"now as an engineer."* →
   same facts, technical depth + the open billing PR. **Same question, two worlds.**
5. **Punchline (10s).** *"Nobody synced. The brain captured it, the graph shows it, my AI translated
   it to my context. That's a company brain — and it's a RocketRide pipeline with no custom code."*

## Act 2 — "give me a task that won't conflict" (Neo4j)
Pre-flight extras: `docker start cb-neo4j` (or the `docker run` from the README); open Neo4j Browser
at **http://localhost:7474** (neo4j / companybrain) next to Obsidian.
1. **Set the scene (15s).** It's release night, ~20 open issues, and four teammates are already
   mid-flight. Show it (two terminals via the hook, or scripted):
   `log-activity --person charlie --working-on cloud-billing`, `josh→observability`,
   `ryan→vector-store`, `dylan→warm-pool`. *"Four people, four features in flight — some not even pushed."*
2. **Show the graph (15s).** In Neo4j Browser run
   `MATCH (p:Person)-[:WORKING_ON]->(f:Feature) RETURN p,f` → charlie/josh/ryan/dylan each wired to
   their feature. *"This is everyone's live work, from open PRs and their Claude Code sessions."*
3. **Ask for a task (20s).** In Claude Code: *"ask the company brain for a task I can pick up tonight
   that won't conflict with anyone."* → `plan_task` returns a safe issue (e.g. **#11 healthz**) and
   **"avoid billing / observability / vector-store / warm-pool — Charlie, Josh, Ryan, Dylan are on them."**
4. **Pick it up — and log it *through a pipeline* (20s).** In Claude Code: *"ok, log that I'm taking
   #11."* → the `log_activity` tool fires **`log.pipe`** (deep agent + GitHub) which resolves #11 → the
   `health` feature and returns a presence record; the client commits it to the vault + Neo4j. Re-run
   the Neo4j query → a **`krish → health`** edge appears; `presence/krish.md` now links
   `[[features/health]]` in Obsidian. *"I picked it up, and a RocketRide pipeline recorded it into the
   brain — live."*
5. **Close the loop (15s).** Ask again: *"now what can I pick up that won't conflict?"* → it **no longer
   recommends #11** and says to **avoid `health` — Krish is on it.** *"The brain just routed the next
   person around me. No standup, no Slack — the pipeline kept everyone in sync."*
6. **Punchline (10s).** *"It didn't guess — it read who's touching what from open PRs and live edits,
   in a Neo4j graph, and routed me around the collision. That standup just disappeared."*

## Fallbacks (if something hiccups on stage)
- **`log_activity` errors / `log.pipe` returns junk:** the tool auto-falls-back to a deterministic
  resolver and still updates both graphs (the reply says `via fallback`). CLI equivalent:
  `python3 companybrain.py log-issue --person krish --issue 11`.
- **Neo4j down / `plan` errors:** `plan` falls back to LLM-over-vault reasoning; or run
  `python3 sync_neo4j.py` to print the conflict summary directly (no agent needed).
- **`make_news.sh`/GitHub slow:** skip it — the baseline graph already tells the story; just do the
  capture + translate beats on existing PRs.
- **Engine wedged** (repeated runs): restart the local engine, then re-run `capture` once to prime.
- **Claude Code MCP not answering:** fall back to the CLI — `python3 companybrain.py ask "…" -p sales`
  — same brain, same answer. Or just open the note in `vault/` (it's only markdown).
- **Capture returns no JSON:** re-run; the agent occasionally wraps output — `companybrain.py`
  tolerates fences, but a second run is the fastest fix.

## Reset between runs
```bash
git checkout -- vault/                 # restore the committed baseline vault
claude mcp list                        # confirm company-brain still ✔ Connected
```
