#!/usr/bin/env bash
# Refuse to cut a release from a main that CI has not blessed.
#
# GH_TOKEN and REPOSITORY come from the calling step's env.
set -euo pipefail

SHA=$(git rev-parse HEAD)

# Keyed on workflow file paths rather than check-run names, which are job names
# and drift. The deploy workflows (release.yml's own, pages.yml) are
# deliberately absent: a staging hiccup should not block cutting a release.
REQUIRED="test-backend.yml playwright.yml test-docker-compose.yml zizmor.yml opa.yml deploy-checks.yml test-action.yml build-proc-sampler.yml"

FAILED=0
AT_HEAD=0

for workflow in $REQUIRED; do
  RUNS=$(gh api \
    "repos/${REPOSITORY}/actions/workflows/${workflow}/runs?branch=main&per_page=20" \
    --jq '.workflow_runs[] | [.head_sha, .status, .conclusion] | @tsv')

  LINE=$(echo "$RUNS" | awk -F'\t' -v s="$SHA" '$1 == s {print; exit}')
  if [ -n "$LINE" ]; then
    AT_HEAD=$((AT_HEAD + 1))
    SCOPE="on $SHA"
  else
    # A path-filtered workflow (opa.yml, deploy-checks.yml, test-action.yml,
    # build-proc-sampler.yml) legitimately does not run for a commit that
    # touches nothing it watches. Its last completed run on main is still the
    # current truth about that subsystem, so fall back to it rather than
    # treating "did not run" as "not green".
    LINE=$(echo "$RUNS" | awk -F'\t' '$2 == "completed" {print; exit}')
    SCOPE="on main (not triggered by $SHA)"
  fi

  if [ -z "$LINE" ]; then
    echo "::warning::${workflow} has never completed a run on main; skipping it."
    continue
  fi

  STATUS=$(echo "$LINE" | cut -f2)
  CONCLUSION=$(echo "$LINE" | cut -f3)
  if [ "$STATUS" != "completed" ]; then
    echo "::error::${workflow} is still ${STATUS} ${SCOPE}."
    FAILED=1
  elif [ "$CONCLUSION" != "success" ] && [ "$CONCLUSION" != "skipped" ]; then
    echo "::error::${workflow} concluded '${CONCLUSION}' ${SCOPE}."
    FAILED=1
  else
    echo "${workflow}: ${CONCLUSION} ${SCOPE}."
  fi
done

# Guarantees the commit being released actually got CI, rather than every
# required workflow silently falling back to an older run.
if [ "$AT_HEAD" = "0" ]; then
  echo "::error::No required workflow ran against ${SHA} at all."
  FAILED=1
fi

if [ "$FAILED" = "1" ]; then
  echo "::error::main is not green — refusing to release."
  exit 1
fi
echo "main is green at ${SHA}."
