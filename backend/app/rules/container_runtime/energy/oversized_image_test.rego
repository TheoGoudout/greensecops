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

# Rego normalises a division that lands on a whole number back to an integer,
# and sprintf's %f rejects an integer — so a size that divided evenly used to
# render the finding as "final image is %!f(int=2) GB" to the user. Sizes are
# reported as rounded integers now; this pins the case that broke.
test_evidence_is_readable_when_the_size_divides_evenly if {
	violations := oversized_image.violations with input as {"build": {"image_size_bytes": 2000000000}}
	some v in violations
	v.evidence == "final image is 2000 MB"
}
