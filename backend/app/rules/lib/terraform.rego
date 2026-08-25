# Shared helpers for the iac_terraform rules.
#
# python-hcl2 parses HCL; it does not evaluate it. An attribute written
# `storage_encrypted = var.encrypt` therefore arrives as the *string*
# `"${var.encrypt}"`, and one written `deletion_protection = true` arrives as
# the boolean `true`. A rule that only tests `== true` reports every
# parameterised module as insecure, and a rule that only tests `!= false`
# reports nothing.
#
# Four rules — rds_no_deletion_protection, cloudwatch_log_group_no_retention,
# sqs_queue_unencrypted and s3_public_access_block_disabled — each carried a
# private copy of the "a reference is not false" test, with four slightly
# different bodies. rds_not_encrypted carried none, so `storage_encrypted =
# var.encrypt` fired it at high severity. This is the one copy.
#
# Carries no METADATA and emits no `violations`; `rego_metadata.iter_rule_files`
# skips everything under `lib/`.
package greensecops.lib.terraform

import rego.v1

# True when the value is an unresolved reference — a variable, a local, another
# resource's attribute, or any expression hcl2 handed back as interpolation
# text. The module author made a decision the parser cannot see, and reporting
# it as `false` reports the decision rather than the configuration.
is_reference(value) if {
	is_string(value)
	contains(value, "${")
}

is_reference(value) if {
	is_string(value)
	regex.match(`^(var|local|each|count|data|module)\.`, trim_space(value))
}

# True when an attribute reads as "on": literally true, the string "true" that
# JSON Terraform configurations produce, or a reference this cannot resolve.
#
# Deliberately generous about references: a rule asking "is this protection
# switched on" should stay silent about a module that takes the answer as an
# input, because the answer is in the caller and this document is not it.
is_enabled(value) if value == true

is_enabled(value) if {
	is_string(value)
	lower(trim_space(value)) == "true"
}

is_enabled(value) if is_reference(value)

# The negation, for a rule whose finding is "this flag is *set*" rather than
# "this flag is missing" — a reference is not a positive assertion either.
is_disabled(value) if value == false

is_disabled(value) if {
	is_string(value)
	lower(trim_space(value)) == "false"
}
