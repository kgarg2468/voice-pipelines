#!/usr/bin/env bash
# Seed the deterministic demo repo for the Company Brain.
# RocketRide-themed activity by two personas: Charlie (engineer) + Dana (sales/PM).
# Idempotent-ish: safe to re-run; it skips repo creation if the repo already exists.
#
#   ./seed_repo.sh            # uses default repo name below
#   REPO=kgarg2468/foo ./seed_repo.sh
set -euo pipefail

REPO="${REPO:-kgarg2468/company-brain-demo}"
OWNER="${REPO%/*}"
WORK="$(mktemp -d)"
echo "==> Repo: $REPO   workdir: $WORK"

# 1) Create the private repo (skip if it exists)
if gh repo view "$REPO" >/dev/null 2>&1; then
  echo "==> $REPO already exists — reusing it."
else
  gh repo create "$REPO" --private \
    --description "RocketRide internal monorepo (Company Brain demo data — synthetic)" >/dev/null
  echo "==> created $REPO"
fi

# 2) Seed main with a small, believable source tree
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-$(gh auth token 2>/dev/null)}}"
REMOTE="https://x-access-token:${TOKEN}@github.com/$REPO.git"
git clone "$REMOTE" "$WORK" >/dev/null 2>&1
cd "$WORK"
git config user.name  "RocketRide Bot" >/dev/null
git config user.email "bot@rocketride.ai" >/dev/null

mkdir -p src/engine src/nodes src/billing src/observability
cat > README.md <<'EOF'
# RocketRide — pipeline engine (internal)

Monorepo for the RocketRide AI-pipeline engine, nodes, billing, and observability.
> Synthetic data for the **Company Brain** demo. People: **Charlie** (engineer),
> **Dana** (sales / PM).
EOF
echo "def authenticate(task):\n    # global shared key (to be replaced)\n    return True\n" > src/engine/auth.py
echo "RESIDENT_TTL = 900  # seconds\n# warm pool of engine workers\n" > src/engine/warm_pool.py
echo "# tool_github node — GitHub repository operations exposed to agents\n" > src/nodes/tool_github.py
echo "# cloud-run billing meter (stub)\n" > src/billing/meter.py
echo "# pipeline trace events (stub)\n" > src/observability/trace.py
git add -A && git commit -q -m "Initial RocketRide engine skeleton" && git push -q origin HEAD:main
echo "==> seeded main"

# 3) Labels (persona + feature + type) so the brain can wire the graph deterministically
mklabel(){ gh label create "$1" --repo "$REPO" --color "$2" --force >/dev/null 2>&1 || true; }
mklabel "person:charlie"        "1f6feb"
mklabel "person:dana"           "a371f7"
mklabel "feature:auth-refactor" "0e8a16"
mklabel "feature:warm-pool"     "0e8a16"
mklabel "feature:tool-github"   "0e8a16"
mklabel "feature:cloud-billing" "0e8a16"
mklabel "feature:observability" "0e8a16"
mklabel "type:translation"      "d93f0b"
echo "==> labels created"

# 4) Issues  (created first → low numbers)
iss(){ gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3" --json number -q .number 2>/dev/null \
       || gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3" | sed 's#.*/##'; }
I_AUTH=$(iss "Engine rejects local connections without an API key" \
  "Reported by **Charlie** (engineer). The OSS engine returns \`No authorization provided\` when a client connects to a local engine without a key. We need real per-task auth instead of a single shared global key." \
  "person:charlie,feature:auth-refactor")
I_WARM=$(iss "Warm pool wedges after ~40 resident workers" \
  "**Charlie**: under repeated warm-pool runs the engine wedges once residents pass ~40 (ttl 900s). Needs a restart/prime/retry path and a resident cap." \
  "person:charlie,feature:warm-pool")
I_XLATE=$(iss "Sales can't explain the auth change to customers" \
  "**Dana** (sales/PM): I keep getting asked about Charlie's auth refactor on customer calls and I can't translate it. I need a one-line, non-technical explanation of what changed and why customers should care." \
  "person:dana,feature:auth-refactor,type:translation")
I_BILL=$(iss "Bill cloud runs per pipeline-second" \
  "**Dana**: prospects want usage-based pricing. We should meter cloud pipeline runs per second and expose it on invoices." \
  "person:dana,feature:cloud-billing")
echo "==> issues: auth=#$I_AUTH warm=#$I_WARM xlate=#$I_XLATE bill=#$I_BILL"

# 5) Pull requests  (branch -> edit -> push -> open -> maybe merge)
open_pr(){ # $1 branch  $2 file  $3 newline  $4 title  $5 body  $6 labels
  git checkout -q -b "$1" main
  printf '%s\n' "$3" >> "$2"
  git add -A && git commit -q -m "$4" && git push -q origin "$1"
  gh pr create --repo "$REPO" --base main --head "$1" --title "$4" --body "$5" --label "$6" >/dev/null
  gh pr view "$1" --repo "$REPO" --json number -q .number
}
merge_pr(){ gh pr merge "$1" --repo "$REPO" --merge --delete-branch=false >/dev/null 2>&1 || \
            gh pr merge "$1" --repo "$REPO" --squash --admin >/dev/null 2>&1 || true; }

P_AUTH=$(open_pr "auth-refactor" src/engine/auth.py \
  "def authenticate(task):\n    return validate_scoped_key(task.api_key)  # per-task key" \
  "Auth refactor: per-task API key validation" \
  "By **Charlie**. Closes #$I_AUTH. Each running task now authenticates with its own scoped API key instead of one shared global key — local, on-prem, and cloud connect securely." \
  "person:charlie,feature:auth-refactor")
merge_pr "$P_AUTH"

P_WARM=$(open_pr "warm-pool-fix" src/engine/warm_pool.py \
  "MAX_RESIDENTS = 32\ndef reap():\n    restart_prime_retry()" \
  "Fix warm-pool wedge under repeated runs" \
  "By **Charlie**. Closes #$I_WARM. Caps residents at 32 and adds restart→prime→retry so repeated runs no longer wedge the engine." \
  "person:charlie,feature:warm-pool")
merge_pr "$P_WARM"

P_GH=$(open_pr "tool-github-readonly" src/nodes/tool_github.py \
  "READ_ONLY_DEFAULT = True  # block writes for agents" \
  "Read-only mode for the GitHub tool node" \
  "By **Charlie**. Adds a \`readOnly\` flag to the GitHub tool node so agents can read issues/PRs/commits but never mutate a repo." \
  "person:charlie,feature:tool-github")
merge_pr "$P_GH"

P_BILL=$(open_pr "cloud-billing" src/billing/meter.py \
  "def meter(run):\n    return run.seconds * PRICE_PER_SECOND  # WIP" \
  "Metered billing for cloud pipeline runs" \
  "By **Charlie**, requested by **Dana**. Relates to #$I_BILL. Per-second metering of cloud runs, surfaced on invoices. Still in review." \
  "person:charlie,person:dana,feature:cloud-billing")
# NOTE: P_BILL is intentionally LEFT OPEN (a PR in flight) for the demo.

git checkout -q main
echo ""
echo "==> SEED COMPLETE for $REPO"
echo "    issues: auth #$I_AUTH | warm #$I_WARM | xlate #$I_XLATE | bill #$I_BILL"
echo "    PRs(merged): auth #$P_AUTH | warm #$P_WARM | github #$P_GH"
echo "    PRs(open):   billing #$P_BILL"
echo "    (Run make_news.sh later to create+merge the live 'streaming trace' PR on stage.)"
rm -rf "$WORK"