#!/usr/bin/env bash
# One preview comment per pull request, edited in place.
#
# A comment per push would bury the review under deployment noise on any branch
# that takes more than a couple of rounds, which is most of them. The marker is
# how the comment finds itself again on the next run.
#
# REPO, PR, the three URLs and SHA come from the calling step's env.
set -euo pipefail
marker='<!-- pages-preview -->'

body=$(cat <<BODY
${marker}
### Preview

| Surface | URL |
|---|---|
| Landing | ${LANDING_URL:-—} |
| Dashboard | ${FRONTEND_URL:-—} |
| Documentation | ${DOCS_URL:-—} |

Built from \`${SHA}\` against the **staging** API and marked
\`noindex\`. These are Worker versions, not deployments — the staging
site itself still serves \`main\`.
BODY
)

# --paginate runs the filter once per page, so a match on any page prints an id
# and the rest print nothing. Take the first, without a pipe: `| head -1` would
# close gh's stdout early on a long thread and turn the SIGPIPE into a failure
# under `set -o pipefail`.
ids=$(gh api "repos/${REPO}/issues/${PR}/comments" --paginate \
  --jq "map(select(.body | startswith(\"${marker}\"))) | .[0].id // empty")
id=${ids%%$'\n'*}

if [ -n "${id}" ]; then
  gh api -X PATCH "repos/${REPO}/issues/comments/${id}" -f body="${body}"
else
  gh api -X POST "repos/${REPO}/issues/${PR}/comments" -f body="${body}"
fi
