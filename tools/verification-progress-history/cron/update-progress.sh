#!/usr/bin/env bash
#
# Weekly cron wrapper for progress_history.py: fetch the latest commits, add
# this week's sample (idempotent via --resume), regenerate the burn-up chart,
# and commit the updated data if it changed.
#
# Install: copy this file (one copy per project), edit the CONFIG block,
# `chmod +x`, and add the matching line from example.crontab. Run it once by
# hand first to confirm the environment is right (PATH, HOME, git credentials,
# and the probe binary all resolve for the cron user).
#
# See the README section "Scheduling weekly updates (cron)".

set -euo pipefail

# --- CONFIG (edit these) ---------------------------------------------------
NAME="dalek-verus"                                  # data/<NAME>/ subdir
REPO_URL="https://github.com/<org>/dalek-verus"     # the project under analysis
REPO_ROOT="/opt/vph/veritooling"                    # this repo's checkout (holds data/)
WORK_CLONE="/var/lib/vph/${NAME}"                   # persistent clone, reused across runs
SAMPLE_TIMEOUT=7200                                 # per-sample verify timeout (s)
# Probe pipeline flags for THIS project (see the README "Run" examples):
PIPELINE_ARGS=(--pipeline verus --project-subdir curve25519-dalek --package curve25519-dalek)
# Where to publish the refreshed data + chart. A dedicated bot branch by
# default (open a PR from it); adapt this to your workflow.
PUSH_BRANCH="data/vph-${NAME}"
GIT_AUTHOR_NAME="vph-bot"
GIT_AUTHOR_EMAIL="vph@example.com"
# cron runs with a minimal environment; make the probe + toolchain resolvable.
export HOME="${HOME:-/home/vph}"
export PATH="$HOME/.elan/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
# ---------------------------------------------------------------------------

TOOL="$REPO_ROOT/tools/verification-progress-history"
DATA_REL="tools/verification-progress-history/data/$NAME"
JSONL="$TOOL/data/$NAME/progress.jsonl"
STAMP() { date -u +%FT%TZ; }

# Never let two runs overlap: a verify can take hours, and cron may fire again
# (or someone may run it by hand) before the previous run finishes.
exec 9>"/var/lib/vph/${NAME}.lock"
flock -n 9 || { echo "[$(STAMP)] $NAME: another run in progress; exiting"; exit 0; }

cd "$TOOL"

# --resume: fetch new commits into the reused clone and sample only those not
#   already recorded (upsert by SHA); a week with no new commit adds nothing.
#   (Add --retry-failed if you want the cron to re-attempt past failures too.)
# --fail-on-error: exit non-zero if any sample run this invocation is not `ok`.
# We capture that code rather than letting `set -e` abort, so a failure is still
# published (a `verify_error` row shows as a gap; the plot omits it) and the
# local/remote --resume state stays in sync -- then we exit non-zero at the end
# to surface the broken week to cron mail / the log monitor.
rc=0
python3 progress_history.py "$REPO_URL" \
  "${PIPELINE_ARGS[@]}" \
  --work-clone "$WORK_CLONE" --resume --fail-on-error \
  --cadence weekly --sample-timeout "$SAMPLE_TIMEOUT" || rc=$?

# Refresh the burn-up (SVG always; PNG when a converter is on PATH).
python3 plot_progress.py "$JSONL" --png

# Commit + push whenever the data or chart changed (including a recorded gap).
cd "$REPO_ROOT"
if git diff --quiet -- "$DATA_REL/"; then
  echo "[$(STAMP)] $NAME: no change; nothing to commit"
else
  git add "$DATA_REL/"
  git -c "user.name=$GIT_AUTHOR_NAME" -c "user.email=$GIT_AUTHOR_EMAIL" \
      commit -m "data($NAME): weekly progress sample $(date -u +%F)"
  git push origin "HEAD:refs/heads/$PUSH_BRANCH"
  echo "[$(STAMP)] $NAME: pushed update to $PUSH_BRANCH"
fi

# Non-zero if any sample this run was not ok, so monitoring notices.
exit "$rc"
