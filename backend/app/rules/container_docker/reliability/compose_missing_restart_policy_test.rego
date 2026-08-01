package greensecops.container_docker.reliability.compose_missing_restart_policy_test

import data.greensecops.container_docker.reliability.compose_missing_restart_policy
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_when_restart_absent if {
	violations := compose_missing_restart_policy.violations with input as _compose({"api": _service({})})
	count(violations) == 1
}

test_no_violation_with_unless_stopped if {
	violations := compose_missing_restart_policy.violations with input as _compose({"api": _service({"restart": "unless-stopped"})})
	count(violations) == 0
}

test_no_violation_with_deploy_restart_policy if {
	violations := compose_missing_restart_policy.violations with input as _compose({"api": _service({"deploy": {"restart_policy": {"condition": "any"}}})})
	count(violations) == 0
}

# `restart: "no"` is the default spelled out — it is not a policy.
test_violation_when_restart_is_explicitly_no if {
	violations := compose_missing_restart_policy.violations with input as _compose({"api": _service({"restart": "no"})})
	count(violations) == 1
}

# An override fragment restates only what it changes; the base file may well
# declare a restart policy, so absence here is not evidence of anything.
test_no_violation_on_a_compose_override_fragment if {
	violations := compose_missing_restart_policy.violations with input as {"compose_files": [{
		"__docker_file": "compose.override.yml",
		"is_override": true,
		"services": {"api": _service({})},
	}]}
	count(violations) == 0
}
