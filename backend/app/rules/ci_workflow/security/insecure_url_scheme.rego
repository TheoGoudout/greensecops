# METADATA
# title: Plaintext download in a run step
# description: "A run step fetches over http://. Anything on the path between the runner and the host can read and rewrite the response, and a download is usually a script or a binary the job then executes — so a rewritten response is code execution on the runner with whatever the job's token can reach. Loopback addresses are excluded: traffic to a service the job started itself never leaves the machine."
# custom:
#   severity: high
#   severity_weight: 2.0
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: curl -fsSL http://example.com/install.sh | bash
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: curl -fsSL https://example.com/install.sh | bash
#     fix: |
#       Use https://. If the host genuinely has no TLS, download over https from a mirror that does, or verify the payload against a checksum pinned in the workflow — an unauthenticated plaintext download of an executable is the weakest link in an otherwise pinned supply chain.
package greensecops.ci_workflow.security.insecure_url_scheme

import rego.v1

# Traffic to a service the job started itself never leaves the machine, so TLS
# would protect nothing. This repository's own CI talks to its containers on
# http://localhost:8000.
_loopback_pattern := `^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|host\.docker\.internal)([:/]|$)`

_code(run) := regex.replace(run, `#[^\n]*`, "")

# Backslash continuations first, so `curl \\<newline>  http://...` is one line by
# the time the fetch check below asks what is on it.
_logical_lines(run) := split(regex.replace(_code(run), `\\\n\s*`, " "), "\n")

# The URL has to be an argument to something that fetches it. Matching any
# `http://` substring reported an XML namespace in a heredoc
# (`xmlns="http://maven.apache.org/POM/4.0.0"`), a licence URL and a link in an
# echoed message as plaintext downloads — at high severity, with a fix that
# rewrites a namespace nobody may rewrite.
# Anchored at a *command position* — line start, or after a pipe, a separator,
# or a wrapper like `sudo`. Matching the verb anywhere on the line is not
# enough: `http` is both an HTTPie invocation and the first four characters of
# every URL, so an unanchored alternation matches the very string it is meant
# to qualify, and `echo "see http://..."` reports itself.
_fetch_command := `(?i)(^\s*|[|;&(]\s*|&&\s*|\|\|\s*|\b(sudo|env|time|xargs|nohup)\s+)(curl|wget|aria2c|http|https|pip3?|python3?\s+-m\s+pip|npm|yarn|pnpm|bun|apt|apt-get|add-apt-repository|apk|yum|dnf|brew|gem|composer|nuget|helm|kubectl|docker|git|go|cargo|scp|rsync|nix|terraform)\b`

# A set rather than a function returning one value: a step can fetch more than
# one plaintext URL, and each is its own finding.
_plaintext_urls(run) := {url |
	some line in _logical_lines(run)
	regex.match(_fetch_command, line)
	some url in regex.find_n(`http://[^\s'"$)\\;|]+`, line, -1)
	not regex.match(_loopback_pattern, url)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	run := step.run
	is_string(run)
	some url in _plaintext_urls(run)

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "insecure_url_scheme",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' fetches %v over plaintext http. Anything on the path can rewrite the response, and a rewritten script or binary runs on the runner with the job's token.", [step_label, job_name, url]),
		"context": url,
		"discriminator": sprintf("%v:%v:%v", [job_name, step_index, url]),
	}
}
