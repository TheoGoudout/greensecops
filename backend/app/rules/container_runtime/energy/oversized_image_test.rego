package greensecops.container_runtime.energy.oversized_image_test

import data.greensecops.container_runtime.energy.oversized_image
import rego.v1

test_violation_for_a_multi_gigabyte_image if {
	violations := oversized_image.violations with input as {"build": {"image_size_bytes": 2400000000}}
	count(violations) == 1
}

test_no_violation_for_a_small_image if {
	violations := oversized_image.violations with input as {"build": {"image_size_bytes": 180000000}}
	count(violations) == 0
}
