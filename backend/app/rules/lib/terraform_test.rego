package greensecops.lib.terraform_test

import data.greensecops.lib.terraform as tf
import rego.v1

test_is_enabled_for_a_literal_true if {
	tf.is_enabled(true)
}

test_is_enabled_for_the_json_string_form if {
	tf.is_enabled("true")
	tf.is_enabled("True")
}

# The case that made rds_not_encrypted fire on every parameterised module.
test_is_enabled_for_an_interpolated_variable if {
	tf.is_enabled("${var.encrypt}")
}

test_is_enabled_for_a_bare_reference if {
	tf.is_enabled("var.encrypt")
	tf.is_enabled("local.encrypt")
	tf.is_enabled("data.aws_kms_key.this.enabled")
}

test_is_not_enabled_for_false if {
	not tf.is_enabled(false)
	not tf.is_enabled("false")
}

test_is_not_enabled_for_an_unrelated_string if {
	not tf.is_enabled("maybe")
}

test_is_disabled_only_for_an_explicit_false if {
	tf.is_disabled(false)
	tf.is_disabled("false")
	not tf.is_disabled("${var.encrypt}")
	not tf.is_disabled(true)
}

test_is_reference_distinguishes_text_from_a_reference if {
	tf.is_reference("${var.x}")
	tf.is_reference("module.vpc.id")
	not tf.is_reference("a-literal-name")
	not tf.is_reference(true)
}
