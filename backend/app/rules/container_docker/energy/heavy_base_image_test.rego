package greensecops.container_docker.energy.heavy_base_image_test

import data.greensecops.container_docker.energy.heavy_base_image
import rego.v1

_stage(index, image, tag, final) := {
	"index": index,
	"image": image,
	"tag": tag,
	"name": null,
	"is_final": final,
	"__start_line__": 1,
	"__end_line__": 5,
}

_df(stages) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": stages[count(stages) - 1].index,
	"stages": stages,
	"instructions": [],
}]}

test_violation_for_full_python if {
	violations := heavy_base_image.violations with input as _df([_stage(0, "python", "3.12", true)])
	count(violations) == 1
}

test_no_violation_for_slim_python if {
	violations := heavy_base_image.violations with input as _df([_stage(0, "python", "3.12-slim", true)])
	count(violations) == 0
}

test_no_violation_for_alpine_node if {
	violations := heavy_base_image.violations with input as _df([_stage(0, "node", "22-alpine", true)])
	count(violations) == 0
}

test_violation_recognises_a_registry_qualified_image if {
	violations := heavy_base_image.violations with input as _df([_stage(0, "docker.io/library/debian", "bookworm", true)])
	count(violations) == 1
}

# A builder on a full image is correct — only the shipped stage is judged.
test_no_violation_when_only_the_builder_is_heavy if {
	violations := heavy_base_image.violations with input as _df([
		_stage(0, "python", "3.12", false),
		_stage(1, "python", "3.12-slim", true),
	])
	count(violations) == 0
}

test_no_violation_for_an_image_with_no_slim_variant if {
	violations := heavy_base_image.violations with input as _df([_stage(0, "alpine", "3.21", true)])
	count(violations) == 0
}
