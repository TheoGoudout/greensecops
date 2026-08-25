package greensecops.iac_ansible.reliability.galaxy_requirement_unpinned_test

import data.greensecops.iac_ansible.reliability.galaxy_requirement_unpinned as rule
import rego.v1

_file(requirements) := {"files": [{
	"__ansible_file": "requirements.yml",
	"kind": "requirements",
	"requirements": requirements,
}]}

test_violation_for_a_collection_without_version if {
	violations := rule.violations with input as _file({"collections": [{"name": "amazon.aws", "__start_line__": 8}]})
	count(violations) == 1
	some v in violations
	v.line_start == 8
	v.discriminator == "collections/amazon.aws"
}

test_violation_for_the_shorthand_form if {
	violations := rule.violations with input as _file({"collections": ["amazon.aws"]})
	count(violations) == 1
	some v in violations
	v.discriminator == "collections/amazon.aws"
}

test_no_violation_when_pinned if {
	violations := rule.violations with input as _file({"collections": [{"name": "amazon.aws", "version": ">=9.0.0,<12.0.0"}]})
	count(violations) == 0
}

test_roles_are_checked_too if {
	violations := rule.violations with input as _file({"roles": [{"name": "geerlingguy.docker"}]})
	count(violations) == 1
	some v in violations
	v.discriminator == "roles/geerlingguy.docker"
}

test_each_entry_is_its_own_finding if {
	violations := rule.violations with input as _file({"collections": [{"name": "a.b"}, {"name": "c.d"}]})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"dependencies": []}
	count(violations) == 0
}
