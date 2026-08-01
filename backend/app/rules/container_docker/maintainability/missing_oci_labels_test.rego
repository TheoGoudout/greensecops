package greensecops.container_docker.maintainability.missing_oci_labels_test

import data.greensecops.container_docker.maintainability.missing_oci_labels
import rego.v1

_stage(index, final) := {"index": index, "name": null, "is_final": final, "__start_line__": 1, "__end_line__": 9}

_inst(keyword, value, stage) := {
	"instruction": keyword,
	"value": value,
	"stage": stage,
	"__start_line__": 2,
	"__end_line__": 2,
}

_df(stages, instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": stages[count(stages) - 1].index,
	"stages": stages,
	"instructions": instructions,
}]}

test_violation_when_no_labels_at_all if {
	violations := missing_oci_labels.violations with input as _df(
		[_stage(0, true)],
		[_inst("COPY", ". /app", 0)],
	)
	count(violations) == 1
}

test_no_violation_with_source_label if {
	violations := missing_oci_labels.violations with input as _df(
		[_stage(0, true)],
		[_inst("LABEL", "org.opencontainers.image.source=\"https://github.com/example/app\"", 0)],
	)
	count(violations) == 0
}

test_violation_when_only_an_unrelated_label_is_set if {
	violations := missing_oci_labels.violations with input as _df(
		[_stage(0, true)],
		[_inst("LABEL", "maintainer=\"platform@example.com\"", 0)],
	)
	count(violations) == 1
}

# A label on the builder stage does not reach the shipped image.
test_violation_when_label_only_in_builder_stage if {
	violations := missing_oci_labels.violations with input as _df(
		[_stage(0, false), _stage(1, true)],
		[_inst("LABEL", "org.opencontainers.image.source=\"https://github.com/example/app\"", 0)],
	)
	count(violations) == 1
}
