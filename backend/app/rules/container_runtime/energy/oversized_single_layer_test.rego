package greensecops.container_runtime.energy.oversized_single_layer_test

import data.greensecops.container_runtime.energy.oversized_single_layer
import rego.v1

# Mirrors the DockerLayer objects the Action ships: index, size_bytes and the
# instruction *keyword* only — `docker history`'s literal RUN text is discarded
# on the runner because it routinely contains build args and credentials.

_build(total, layers) := {"build": {"image_size_bytes": total, "layers": layers}}

_layer(index, size) := {"index": index, "size_bytes": size, "instruction": "RUN"}

test_violation_when_one_layer_dominates if {
	violations := oversized_single_layer.violations with input as _build(900000000, [
		_layer(0, 780000000),
		_layer(1, 120000000),
	])
	count(violations) == 1
	some v in violations
	contains(v.evidence, "layer 0")
}

# Both bars have to be cleared: a layer can be most of the image and still be
# small in absolute terms, which is not a finding.
test_no_violation_when_the_image_is_small if {
	violations := oversized_single_layer.violations with input as _build(50000000, [_layer(0, 45000000)])
	count(violations) == 0
}

test_no_violation_when_layers_are_evenly_sized if {
	violations := oversized_single_layer.violations with input as _build(1200000000, [
		_layer(0, 310000000),
		_layer(1, 320000000),
		_layer(2, 300000000),
		_layer(3, 270000000),
	])
	count(violations) == 0
}

test_violation_exactly_at_the_dominant_share if {
	violations := oversized_single_layer.violations with input as _build(800000000, [
		_layer(0, 400000000),
		_layer(1, 400000000),
	])

	# Both layers are exactly half, so both qualify.
	count(violations) == 2
}

test_no_violation_when_image_size_is_unknown if {
	violations := oversized_single_layer.violations with input as _build(null, [_layer(0, 780000000)])
	count(violations) == 0
}

test_no_violation_when_a_layer_size_is_unknown if {
	violations := oversized_single_layer.violations with input as _build(900000000, [{"index": 0, "size_bytes": null, "instruction": "RUN"}])
	count(violations) == 0
}

test_no_violation_when_there_are_no_layers if {
	violations := oversized_single_layer.violations with input as _build(900000000, [])
	count(violations) == 0
}

test_evidence_names_the_instruction_keyword if {
	violations := oversized_single_layer.violations with input as _build(900000000, [{
		"index": 3,
		"size_bytes": 780000000,
		"instruction": "COPY",
	}])
	some v in violations
	contains(v.evidence, "COPY")
	contains(v.recommendation, "layer 3")
}
