# 🧠 Company Brain

> Capture what happens, store it as a living **Obsidian graph**, and answer it **translated to your
> role** — pulled straight from Claude Code. No syncing meetings. No context-translation tax.

**The problem (YC RFS "company brain" / gbrain):** small teams burn time *syncing* and
*translating* — an engineer re-explaining a merge to a non-technical teammate. The Company Brain
watches the work (GitHub today), writes it into an interlinked note vault, and answers any
teammate's question **in their own context**.

## The on-stage loop
1. **"Charlie just merged a PR — watch."** → `./make_news.sh` then `python3 companybrain.py capture`
   → a new note appears in `vault/`, wired to `[[people/charlie]]` and a feature — **the Obsidian
   graph grows a node live.**
2. **"Now I'm in sales."** → in Claude Code: *"ask the company brain, as sales, what Charlie shipped
   and what it means for customers."* → the deep agent **translates the engineering change into
   sales language.**
3. **Punchline:** *"Nobody synced. The brain captured it, the graph shows it, my AI translated it to
   my world."*

## What's built (zero new nodes)
| Piece | What it is |
|-------|------------|
| `capture.pipe` | `chat → agent_deepagent (+ llm_openai + tool_github read-only) → response_answers`. Reads GitHub, emits interlinked notes as JSON. |
| `brain.pipe` | `chat → agent_deepagent (+ llm_openai) → response_answers`. Answers from the vault, **translated to a persona** (engineer / sales). |
| `companybrain.py` | Client: `capture` writes the vault from GitHub; `ask` routes a question + vault to the brain. |
| `companybrain_mcp.py` | Dependency-free MCP server so **Claude Code** can call `ask_company_brain(question, persona)`. |
| `planner.pipe` | `chat → agent_deepagent (+ llm_openai + db_neo4j) → response_answers`. Recommends a **non-conflicting task** by querying the Neo4j conflict graph. |
| `sync_neo4j.py` | Builds the conflict graph in Neo4j from GitHub (open/draft PRs + changed files) + live presence; has the deterministic `conflict_summary()`. |
| `hooks/report_activity.py` | Claude Code `PostToolUse` hook — auto-reports what each session is editing into `vault/presence/`. Inert unless `COMPANYBRAIN_USER` is set. |
| `companybrain.py` | Client: `capture` (GitHub→vault), `ask` (persona Q&A), `log-activity` (presence), **`plan`** (non-conflicting task). |
| `companybrain_mcp.py` | Dependency-free MCP server: **`ask_company_brain`** + **`plan_task`** for Claude Code. |
| `vault/` | The brain — markdown notes + `[[wikilinks]]` incl. `presence/`. **Open in Obsidian** for the graph view. |
| `seed_repo.sh` / `make_news.sh` | Seed the deterministic demo repo; create the live "new PR" event. |

Everything runs on the **local engine** (`ws://localhost:5565`, OSS key `MYAPIKEY`) + a **local Neo4j**
(Docker) for the planner — no cloud creds.

## Who's working on what → a task that won't conflict
The brain knows in-flight work from **two signals**: pushed work (open/draft PRs + their changed
files) and live edits (each Claude Code session auto-reports via the hook — set
`COMPANYBRAIN_USER=charlie` in one terminal, `=josh` in another). `sync_neo4j.py` turns both into
`(:Person)-[:WORKING_ON]->(:Feature)` edges in **Neo4j** (a sponsor/partner showcase), and `plan`
recommends an open issue in an *untouched* feature — naming what to avoid and who to coordinate with.
The graph view lives at **http://localhost:7474** (Neo4j Browser). The seeded cast is **charlie, krish,
josh, ryan, dylan**; `./seed_more.sh` densifies the repo to ~20 open issues across many features.

## Quickstart
```bash
cd Rocketride-demo-companybrain

# one-time: install/login GitHub CLI, then seed the deterministic private repo
# (if gh is outside PATH, export GH_BIN=/path/to/gh)
gh auth status || gh auth login
./seed_repo.sh

# build the brain from GitHub → writes vault/  (open vault/ in Obsidian)
python3 companybrain.py capture

# ask it, two ways — same question, different context
python3 companybrain.py ask "what did Charlie ship?" --persona engineer
python3 companybrain.py ask "what did Charlie ship, and what does it mean for customers?" --persona sales

# --- who's-working-on-what → non-conflicting task ---
docker run -d --name cb-neo4j -p7474:7474 -p7687:7687 -e NEO4J_AUTH=neo4j/companybrain neo4j:5
./seed_more.sh                      # densify: ~20 open issues, parallel PRs, the full cast
# simulate teammates mid-flight (one per terminal via the hook, or scripted here):
python3 companybrain.py log-activity --person charlie --working-on cloud-billing --files src/billing/meter.py
python3 companybrain.py log-activity --person josh    --working-on observability  --files src/observability/logs.py
python3 companybrain.py log-activity --person ryan    --working-on vector-store    --files src/nodes/vector_store.py
python3 companybrain.py log-activity --person dylan   --working-on warm-pool        --files src/engine/warm_pool.py
python3 companybrain.py build-vault  # deterministic dense vault + Neo4j graph (1:1)
python3 companybrain.py plan "what can I pick up tonight that won't conflict with anyone?"
#   → picks a safe issue (e.g. #11 healthz) and says "avoid billing/observability/vector-store/warm-pool"

# wire it to Claude Code (already registered at user scope; exposes ask_company_brain + plan_task):
#   claude mcp add company-brain --scope user -- python3 "$(pwd)/companybrain_mcp.py"
# then in any session: "ask the company brain for a task that won't conflict with anyone"
```

## Status
| Stage | State |
|---|---|
| capture / ask / plan pipelines run on local engine | ✅ |
| `capture` → interlinked vault from GitHub | ✅ |
| `ask` persona translation (engineer / sales) | ✅ |
| presence (hook + `log-activity`) → `vault/presence/` | ✅ |
| Neo4j conflict graph + `plan` non-conflicting task | ✅ |
| MCP `ask_company_brain` + `plan_task` `✔ Connected` | ✅ |
| Live `make_news.sh` → capture grows the graph | ✅ wired (run on stage) |
| Obsidian graph (`vault/`) + Neo4j Browser (`:7474`) | ▶︎ open on the projector |

Design + decisions: [`PLAN.md`](PLAN.md). Stage script: [`RUNBOOK.md`](RUNBOOK.md).

## Phase 2 (real internal tool, later)
Swap the local-disk vault for **gbrain** (Garry Tan's brain: PGLite=free local / Supabase=paid) as
the durable store + MCP layer, add **scheduled capture** (cron via the SDK or GitHub webhooks →
`webhook` node), broaden sources beyond GitHub (Slack, docs), and add a `db_neo4j` graph or vector
store for scale. The research backing this is in the team memory.
