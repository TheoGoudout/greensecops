package greensecops.container_docker.reliability.unpinned_base_image_test

import data.greensecops.container_docker.reliability.unpinned_base_image
import rego.v1

_stage(index, image, tag, digest, name) := {
	"index": index,
	"image": image,
	"tag": tag,
	"digest": digest,
	"name": name,
	"is_final": true,
	"__start_line__": 1,
	"__end_line__": 5,
}

_df(stages) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": 0,
	"stages": stages,
	"instructions": [],
}]}

test_violation_when_tag_is_absent if {
	violations := unpinned_base_image.violations with input as _df([_stage(0, "redis", null, null, null)])
	count(violations) == 1
}

test_violation_when_tag_is_latest if {
	violations := unpinned_base_image.violations with input as _df([_stage(0, "python", "latest", null, null)])
	count(violations) == 1
}

test_no_violation_when_pinned_by_digest if {
	violations := unpinned_base_image.violations with input as _df([_stage(0, "python", "3.12-slim", "sha256:abc", null)])
	count(violations) == 0
}

# A version tag is still mutable — the publisher republishes it on every patch
# release — so digest-or-nothing is the contract, matching unpinned_actions.
test_violation_with_a_version_tag_but_no_digest if {
	violations := unpinned_base_image.violations with input as _df([_stage(0, "python", "3.12-slim", null, null)])
	count(violations) == 1
	some v in violations
	v.context == "python:3.12-slim"
}

test_no_violation_for_scratch if {
	violations := unpinned_base_image.violations with input as _df([_stage(0, "scratch", null, null, null)])
	count(violations) == 0
}

# `FROM builder` refers to an earlier stage, not a registry image.
test_no_violation_for_internal_stage_reference if {
	violations := unpinned_base_image.violations with input as _df([
		_stage(0, "python", "3.12-slim", "sha256:abc", "builder"),
		_stage(1, "builder", null, null, null),
	])
	count(violations) == 0
}

test_each_unpinned_stage_gets_its_own_discriminator if {
	violations := unpinned_base_image.violations with input as _df([
		_stage(0, "python", "latest", null, "builder"),
		_stage(1, "node", "latest", null, null),
	])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
