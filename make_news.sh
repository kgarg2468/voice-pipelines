#!/usr/bin/env bash
# The live "Charlie just merged a PR" moment. Creates + merges a fresh PR so the
# next `companybrain.py capture` finds a brand-new event and the Obsidian graph
# grows a node on stage. Deterministic: we control the repo.
#
#   ./make_news.sh
set -euo pipefail
REPO="${REPO:-kgarg2468/company-brain-demo}"
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-$(gh auth token 2>/dev/null)}}"
REMOTE="https://x-access-token:${TOKEN}@github.com/$REPO.git"
WORK="$(mktemp -d)"; STAMP="$(date +%H%M%S 2>/dev/null || echo live)"
BR="observability-trace-$STAMP"

git clone -q "$REMOTE" "$WORK"; cd "$WORK"
git config user.name "RocketRide Bot"; git config user.email "bot@rocketride.ai"
git checkout -q -b "$BR" main
printf 'def stream_trace(run):\n    yield from run.events  # live trace -> observability panel\n' >> src/observability/trace.py
git add -A && git commit -q -m "Stream pipeline trace events to the observability panel"
git push -q origin "$BR"
gh pr create --repo "$REPO" --base main --head "$BR" \
  --title "Stream pipeline trace events to the observability panel" \
  --body "By **Charlie**. Streams live pipeline trace events to the observability panel so users can watch a run unfold in real time." \
  --label "person:charlie,feature:observability" >/dev/null
N=$(gh pr view "$BR" --repo "$REPO" --json number -q .number)
gh pr merge "$N" --repo "$REPO" --merge --delete-branch=false >/dev/null 2>&1 \
  || gh pr merge "$N" --repo "$REPO" --squash --admin >/dev/null 2>&1 || true
cd / && rm -rf "$WORK"
echo "==> Charlie just merged PR #$N (observability trace streaming)."
echo "    Now run:  python3 companybrain.py capture   → watch the graph grow."