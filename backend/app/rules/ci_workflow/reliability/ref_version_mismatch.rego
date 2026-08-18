# METADATA
# title: Version comment disagrees with the pin
# description: "A SHA-pinned action carries a trailing version comment naming a version that commit is not. The comment is the only human-readable half of a pin, so a wrong one is a silent lie in review — a dependency bump can move the SHA across a major version while the comment still claims the old one, and every reader who checks the comment instead of the hash approves the wrong thing."
# custom:
#   severity: low
#   severity_weight: 0.6
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302 # v5.8.0
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302 # v6.2.0
#     action_metadata:
#       "docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302":
#         lookup: ok
#         ref_kind: sha
#         commit_exists: true
#         reachability: reachable
#         tags_at_sha: ["v6", "v6.2.0"]
#         tag_lookup: complete
#     fix: |
#       Correct the comment to the version the SHA actually is. Where the pin itself was the mistake, repin to the commit the intended version resolves to instead — the two halves have to agree, and the SHA is the one that runs.
package greensecops.ci_workflow.reliability.ref_version_mismatch

import rego.v1

_version_like(comment) if regex.match(`^v?[0-9]+(\.[0-9]+)*$`, comment)

# `# v6` beside the commit tagged `v6.2.0` is honest shorthand — the major tag
# and the patch tag point at the same commit. `# v5.8.0` beside `v6.2.0` is not.
_compatible(comment, tag) if tag == comment

_compatible(comment, tag) if startswith(tag, concat("", [comment, "."]))

_any_compatible(tags, comment) if {
	some tag in tags
	_compatible(comment, tag)
}

_reported(uses, comment) := meta if {
	meta := input.__actions__[uses]
	meta.lookup == "ok"

	# `tag_lookup == "partial"` means enumeration was truncated, so a tag we did
	# not see may well match — that is "we do not know", not "mismatch". An
	# empty `tags_at_sha` likewise means no tag sits on this commit, which is
	# normal for a deliberate mid-branch pin and is not this rule's business.
	meta.tag_lookup == "complete"
	count(meta.tags_at_sha) > 0
	not _any_compatible(meta.tags_at_sha, comment)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	uses := step.uses
	comment := step.__uses_comment__
	_version_like(comment)
	meta := _reported(uses, comment)

	violation := {
		"rule": "ref_version_mismatch",
		"severity": "low",
		"category": "reliability",
		"job": job_name,
		"step": uses,
		"step_index": step_index,
		"message": sprintf("Step in job '%v' is commented '%v' but the pinned commit is %v. The comment is the half a reviewer reads; correct it, or repin to the version you meant.", [job_name, comment, concat(", ", sort(meta.tags_at_sha))]),
		"context": comment,
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
