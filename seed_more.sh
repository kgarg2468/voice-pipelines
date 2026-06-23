#!/usr/bin/env bash
# Densify the demo repo: rename dana→krish, add josh/ryan/dylan, ~20 open issues,
# and several parallel PRs so the brain/graph look like a real release night.
# Safe-ish to re-run: labels use --force, issues are guarded by title, PR branches are reset.
set -uo pipefail
REPO="${REPO:-kgarg2468/company-brain-demo}"
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-$(gh auth token 2>/dev/null)}}"
REMOTE="https://x-access-token:${TOKEN}@github.com/$REPO.git"
WORK="$(mktemp -d)"
echo "==> repo=$REPO work=$WORK"

# ---- 1) rename dana → krish (label renames in place, keeps it on existing items) ----
gh label edit "person:dana" --repo "$REPO" --name "person:krish" >/dev/null 2>&1 && echo "renamed person:dana → person:krish" \
  || gh label create "person:krish" --repo "$REPO" --color a371f7 --force >/dev/null 2>&1
# fix Dana → Krish in the bodies that mention her
for N in 3 4; do
  B=$(gh issue view "$N" --repo "$REPO" --json body -q .body 2>/dev/null | sed 's/Dana/Krish/g')
  [ -n "$B" ] && gh issue edit "$N" --repo "$REPO" --body "$B" >/dev/null 2>&1 && echo "issue #$N body Dana→Krish"
done
PB=$(gh pr view 8 --repo "$REPO" --json body -q .body 2>/dev/null | sed 's/Dana/Krish/g')
[ -n "$PB" ] && gh pr edit 8 --repo "$REPO" --body "$PB" >/dev/null 2>&1 && echo "PR #8 body Dana→Krish"

# ---- 2) labels (people + features) ----
mklabel(){ gh label create "$1" --repo "$REPO" --color "$2" --force >/dev/null 2>&1 || true; }
mklabel "person:josh"  "1f6feb"; mklabel "person:ryan" "1f6feb"; mklabel "person:dylan" "1f6feb"
mklabel "person:krish" "a371f7"
for f in pipeline-engine vector-store web-console sdk-python rate-limiting docs scheduler; do mklabel "feature:$f" "0e8a16"; done
echo "==> labels ready"

# ---- 3) ~20 open issues spread across features (mostly unassigned = safe picks) ----
mkissue(){ # title  labels  body
  if gh issue list --repo "$REPO" --state all --search "\"$1\" in:title" --json title -q '.[].title' 2>/dev/null | grep -qxF "$1"; then
    echo "  skip (exists): $1"
  else
    gh issue create --repo "$REPO" --title "$1" --label "$2" --body "$3" >/dev/null 2>&1 && echo "  issue: $1"
  fi
}
# safe-feature issues (no one working these → planner can recommend them)
mkissue "Engine: graceful shutdown on SIGTERM"            "feature:pipeline-engine" "Drain in-flight tasks before exit."
mkissue "Scheduler: add priority lanes"                   "feature:pipeline-engine" "Let urgent pipelines jump the queue."
mkissue "Add per-key rate limiting to the public API"     "feature:rate-limiting"   "Token-bucket per API key."
mkissue "Rate limit: return a Retry-After header"         "feature:rate-limiting"   "Tell clients when to retry."
mkissue "Docs: write the Quickstart for new users"        "feature:docs"            "Zero-to-first-pipeline in 5 minutes."
mkissue "Docs: document the deep-agent node"              "feature:docs"            "Cover tools, subagents, memory."
mkissue "Python SDK: async context manager support"       "feature:sdk-python"      "async with RocketRideClient() as c."
mkissue "Python SDK: typed error classes"                "feature:sdk-python"      "Replace bare RuntimeError."
mkissue "Web console: dark mode"                          "feature:web-console"     "Respect prefers-color-scheme."
mkissue "Web console: pipeline run timeline view"         "feature:web-console"     "Visualize a run's lane events."
mkissue "Health: add /readyz separate from /healthz"      "feature:health"          "Split readiness from liveness."
mkissue "tool_github: support GitHub Enterprise hosts"    "feature:tool-github"     "Configurable base URL."
# hot-feature issues (these features ARE being worked → planner should avoid, names who's on them)
mkissue "Billing: usage dashboard"                        "feature:cloud-billing,person:krish"  "Show metered usage per customer."
mkissue "Vector store: add a Pinecone profile"            "feature:vector-store,person:ryan"    "Second backend after Qdrant."
mkissue "Observability: export traces to OTLP"            "feature:observability,person:josh"   "OpenTelemetry exporter."
mkissue "Warm pool: configurable max residents"           "feature:warm-pool,person:dylan"      "Expose the cap as config."
echo "==> issues seeded"

# ---- 4) parallel PRs (branch → file → push → PR → maybe merge), each from latest origin/main ----
git clone -q "$REMOTE" "$WORK"; cd "$WORK"
git config user.name "RocketRide Bot"; git config user.email "bot@rocketride.ai"
open_pr(){ # branch  file  line  title  body  labels  merge(yes|no)
  git fetch -q origin main; git checkout -q -B "$1" origin/main
  mkdir -p "$(dirname "$2")"; printf '%s\n' "$3" >> "$2"
  git add -A && git commit -q -m "$4"; git push -q -f origin "$1" 2>/dev/null
  gh pr create --repo "$REPO" --base main --head "$1" --title "$4" --body "$5" --label "$6" >/dev/null 2>&1 || true
  N=$(gh pr view "$1" --repo "$REPO" --json number -q .number 2>/dev/null)
  if [ "$7" = "yes" ]; then gh pr merge "$N" --repo "$REPO" --merge >/dev/null 2>&1 || gh pr merge "$N" --repo "$REPO" --squash --admin >/dev/null 2>&1 || true; fi
  echo "  PR #$N [$7] $4"
}
# OPEN PRs → these make their features HOT (work in flight, pushed)
open_pr "obs-structured-logs" src/observability/logs.py "def stream_logs(run): ..." \
  "Stream structured logs to the observability panel" "By **Josh**. Live structured logs alongside traces." "person:josh,feature:observability" no
open_pr "vector-store-qdrant" src/nodes/vector_store.py "class QdrantStore: ..." \
  "Add a Qdrant vector-store node" "By **Ryan**. First vector-store backend." "person:ryan,feature:vector-store" no
open_pr "warm-pool-autoscale" src/engine/warm_pool.py "AUTOSCALE = True" \
  "Warm-pool autoscaling" "By **Dylan**. Scale residents with load." "person:dylan,feature:warm-pool" no
# MERGED PRs → density (AUTHORED/TOUCHES/ABOUT) on already-stable features, no current conflict
open_pr "auth-token-rotation" src/engine/auth.py "def rotate(): ..." \
  "Harden auth token rotation" "By **Josh**. Periodic rotation of scoped keys." "person:josh,feature:auth-refactor" yes
open_pr "tool-github-pagination" src/nodes/tool_github.py "PAGE_SIZE = 100" \
  "tool_github: paginate large result sets" "By **Ryan**. Handle repos with many PRs." "person:ryan,feature:tool-github" yes
open_pr "scheduler-fairness" src/engine/scheduler.py "def fair_share(): ..." \
  "Scheduler fairness fix" "By **Dylan**. Round-robin across tenants." "person:dylan,feature:pipeline-engine" yes
open_pr "docs-overview" docs/overview.md "# RocketRide engine overview" \
  "Docs: engine overview" "By **Krish**. High-level architecture page." "person:krish,feature:docs" yes
cd / && rm -rf "$WORK"
echo "==> SEED_MORE complete"