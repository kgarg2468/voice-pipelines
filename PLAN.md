# Company Brain — RocketRide launch demo #5

> Capture what happens, store it as a living **Obsidian graph**, answer it **translated to your role** — pulled straight from Claude Code. No syncing meetings, no context-translation tax.

## Thesis (the problem we kill)
In a small team everyone burns time **syncing** and **translating** info across role-contexts
(an engineer explaining a merge to a non-technical salesperson). The Company Brain watches the
work (starting with GitHub), writes it into an interlinked markdown brain, and answers any
teammate's question **in their own context**.

## Locked decisions (from scoping)
| # | Decision | Choice |
|---|----------|--------|
| Purpose | Demo first → real internal tool later | **Demo first** |
| Storage | Where the brain lives | **Obsidian vault** (markdown + `[[wikilinks]]`) — *source of truth*; Obsidian graph view = the on-stage visual. No gbrain / Neo4j / Redis / vector store for the demo. |
| Capture trigger | How GitHub gets in | **Manual** (run on stage) via `tool_github` (read-only) |
| Claude bridge | How Claude Code pulls | **Thin local MCP shim** over the RR SDK (primary) + **direct vault-read** (fallback) |
| Translation | engineer ↔ sales ↔ exec | **Explicit persona** chosen at ask time |
| Agent | the "deep agent" | **`agent_deepagent`** |
| LLM | model behind the agents | **`llm_openai`** (key already in `.env`); swap to `llm_anthropic` later |
| Data | reliability on stage | **Seeded, deterministic** GitHub repo we own |
| Run target | engine | **Local engine** at `localhost:5565` (no cloud creds needed) |

**New nodes required: NONE.** Everything is existing RocketRide nodes.

## Architecture — two pipelines + a client that owns the local vault

> **Build refinement:** `tool_filesystem` writes to RocketRide's *account-scoped* file store, not
> local disk. For a live Obsidian graph we want the notes ON the laptop. So the **client**
> (`companybrain.py`) owns `vault/` — the capture agent just *produces* the notes and the client
> writes them. Fewer moving parts, still **zero new nodes**, and Obsidian points straight at `vault/`.

### A. `capture.pipe` — run manually on stage
```
chat(source) → agent_deepagent → response_answers
                   │ (control)
            ┌──────┴───────┐
        llm_openai    tool_github (readOnly, defaultRepo)
```
- **Trigger:** `companybrain.py capture` → `client.chat("Capture the latest…")`.
- **Agent job:** read issues + PRs (open/merged) via `tool_github`; emit a strict JSON object
  `{summary, notes:[{path, content}]}` of interlinked markdown notes (PR / issue / person / feature).
- **Client job:** write each note to `vault/<path>`. Obsidian renders the `[[wikilinks]]` as a graph.

### B. `brain.pipe` — the ask pipeline (behind the MCP shim)
```
chat(source) → agent_deepagent → response_answers
                   │ (control)
              llm_openai
```
- **Input (composed by the client/shim):** `"PERSONA: sales\nQUESTION: …\n\nNOTES:\n<vault notes>"`.
- **Agent job:** answer using only the notes, **translated to the persona**
  (engineer = technical depth + open work; sales = customer value, no jargon), citing PR/issue numbers.

## Vault / graph schema (the brain)
```
vault/
  index.md                 # map-of-content hub linking every section
  people/charlie.md        # type: person
  prs/pr-42.md             # type: pr   (frontmatter: status, url, people[], touches[])
  issues/issue-12.md       # type: issue
  features/auth-refactor.md # type: feature/topic
  decisions/...            # type: decision (optional)
```
Notes carry YAML frontmatter + `[[wikilinks]]` in the body. **The wikilinks are the graph edges**
Obsidian renders. e.g. `prs/pr-42.md` links `[[charlie]]`, `[[auth-refactor]]`, `[[issue-12]]`.

## Seeded demo repo (deterministic)
A private repo `kgarg2468/<name>` seeded with ~6 issues + ~5 PRs (2–3 merged), content referencing
personas **Charlie** (eng) and **Dana** (sales/PM) and a feature **auth-refactor**. `tool_github`
reads it for real → deterministic because we own/freeze it. We also commit a **seeded baseline
vault** so the graph is pre-populated; capture adds the newest PR live.

## Claude Code bridge
`companybrain_mcp.py` — a stdio MCP server exposing one tool `ask_company_brain(question, persona)`
that calls `brain.pipe` over the RR SDK and returns the translated answer. Registered with
`claude mcp add`. Fallback: Claude Code reads `vault/` directly (it's just markdown).

## Edge cases & handling
| Edge case | Handling |
|-----------|----------|
| Capture run twice → dup notes | Notes keyed by **stable filename**; agent upserts. Status change (issue open→resolved) appends a history line — *SUPERSEDES* idea borrowed from palimpsest. |
| Brain mutating the repo | `tool_github` `readOnly: true` — capture can never write to GitHub. |
| Obsidian graph hairball | Small curated seed; capture adds a few well-linked notes, not everything. |
| Live GitHub flakiness / rate limits | We **own + freeze** the repo → deterministic on stage. |
| No cloud creds | Run on the **local engine** (`:5565`). |
| Persona accuracy | **Explicit persona tag** in the question; agent instructions define each lens. |
| Secret handling | `${ROCKETRIDE_*}` via `.env`; GitHub PAT is read-only / fine-grained. |

## On-stage loop
1. *"Charlie just merged a PR — watch."* → run capture → new `[[pr-42]]` note links `[[charlie]]` +
   `[[auth-refactor]]`; **Obsidian graph grows a node live.**
2. *"Now I'm in sales. I ask my Claude Code: what did Charlie ship, and what does it mean for customers?"*
   → Claude Code → brain → **deep agent translates the engineering change into sales language.**
3. Punchline: *"Nobody synced. The brain captured it, the graph shows it, my AI translated it to my world."*

## Build order
1. Seed repo + baseline vault (outward — needs go-ahead).
2. `capture.pipe` + `brain.pipe` via the rocketride pipeline-skills gated lifecycle (design → configure → validate against `:5565`).
3. `companybrain_mcp.py` + register with Claude Code.
4. README (demo script) + RUNBOOK + share/QR step.
