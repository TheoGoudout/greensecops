package greensecops.container_docker.security.compose_missing_no_new_privileges_test

import data.greensecops.container_docker.security.compose_missing_no_new_privileges as no_new_privs
import rego.v1

_compose(services) := {"effective_compose_files": [{
	"__docker_file": "compose.yml",
	"is_override": false,
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_when_security_opt_is_absent if {
	violations := no_new_privs.violations with input as _compose({"api": _service({})})
	count(violations) == 1
	some v in violations
	v.service_name == "api"
}

test_no_violation_when_the_option_is_set if {
	violations := no_new_privs.violations with input as _compose({"api": _service({"security_opt": ["no-new-privileges:true"]})})
	count(violations) == 0
}

test_no_violation_for_the_equals_spelling if {
	violations := no_new_privs.violations with input as _compose({"api": _service({"security_opt": ["no-new-privileges=true"]})})
	count(violations) == 0
}

test_violation_when_the_option_is_explicitly_false if {
	violations := no_new_privs.violations with input as _compose({"api": _service({"security_opt": ["no-new-privileges:false"]})})
	count(violations) == 1
}

test_no_violation_when_set_alongside_other_options if {
	violations := no_new_privs.violations with input as _compose({"api": _service({"security_opt": [
		"seccomp=unconfined",
		"no-new-privileges:true",
	]})})
	count(violations) == 0
}

# A privileged container ignores the flag, and compose_privileged_container
# reports the far larger problem — adding a low-severity note beside it would
# be noise.
test_no_violation_for_a_privileged_service if {
	violations := no_new_privs.violations with input as _compose({"agent": _service({"privileged": true})})
	count(violations) == 0
}

test_no_violation_for_a_non_runnable_service if {
	violations := no_new_privs.violations with input as _compose({"api": {"__start_line__": 2, "__end_line__": 3}})
	count(violations) == 0
}

test_no_violation_for_a_null_service if {
	violations := no_new_privs.violations with input as _compose({"api": null})
	count(violations) == 0
}

# Only the merged configuration reaches this rule; the raw documents beside it
# serve the presence-based rules, which need the file the option is missing
# from to be the file a reader would open.
test_no_violation_on_the_raw_files_of_a_merged_pair if {
	violations := no_new_privs.violations with input as {
		"compose_files": [
			{
				"__docker_file": "compose.yml",
				"is_override": false,
				"services": {"api": _service({})},
			},
			{
				"__docker_file": "compose.override.yml",
				"is_override": true,
				"services": {"api": {"security_opt": ["no-new-privileges:true"]}},
			},
		],
		"effective_compose_files": [{
			"__docker_file": "compose.yml",
			"services": {"api": _service({"security_opt": ["no-new-privileges:true"]})},
		}],
	}
	count(violations) == 0
}

test_each_service_is_its_own_finding if {
	violations := no_new_privs.violations with input as _compose({
		"api": _service({}),
		"worker": _service({}),
		"db": _service({"security_opt": ["no-new-privileges:true"]}),
	})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
