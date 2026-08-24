package greensecops.container_docker.security.compose_service_not_hardened_test

import data.greensecops.container_docker.security.compose_service_not_hardened as hardening
import rego.v1

_compose(services) := {"effective_compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_svc(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

_hardened := {
	"read_only": true,
	"security_opt": ["no-new-privileges:true"],
}

test_violation_when_neither_setting_is_present if {
	violations := hardening.violations with input as _compose({"api": _svc({})})
	count(violations) == 1
	some v in violations
	v.service_name == "api"
	contains(v.message, "read_only: true")
	contains(v.message, "no-new-privileges")
}

test_one_finding_lists_only_what_is_missing if {
	violations := hardening.violations with input as _compose({"api": _svc({"read_only": true})})
	count(violations) == 1
	some v in violations
	v.context == "no-new-privileges:true under security_opt"
}

test_no_violation_when_both_are_set if {
	violations := hardening.violations with input as _compose({"api": _svc(_hardened)})
	count(violations) == 0
}

test_no_violation_for_a_privileged_container if {
	violations := hardening.violations with input as _compose({"api": _svc({"privileged": true})})
	count(violations) == 0
}

test_no_violation_for_a_service_that_runs_nothing if {
	violations := hardening.violations with input as {"effective_compose_files": [{
		"__docker_file": "compose.yml",
		"services": {"base": {"environment": {"X": "1"}}},
	}]}
	count(violations) == 0
}

test_no_new_privileges_accepts_the_equals_form if {
	violations := hardening.violations with input as _compose({"api": _svc({
		"read_only": true,
		"security_opt": ["no-new-privileges=true"],
	})})
	count(violations) == 0
}

# One finding per service, not one per missing setting — the whole point of
# folding the two rules together.
test_one_finding_per_service if {
	violations := hardening.violations with input as _compose({
		"api": _svc({}),
		"worker": _svc({}),
	})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
