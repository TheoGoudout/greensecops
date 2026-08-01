package greensecops.container_docker.reliability.compose_depends_on_without_condition_test

import data.greensecops.container_docker.reliability.compose_depends_on_without_condition
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_for_short_list_form if {
	violations := compose_depends_on_without_condition.violations with input as _compose({"api": _service({"depends_on": ["db"]})})
	count(violations) == 1
}

test_no_violation_for_long_form_with_condition if {
	violations := compose_depends_on_without_condition.violations with input as _compose({"api": _service({"depends_on": {"db": {"condition": "service_healthy"}}})})
	count(violations) == 0
}

test_no_violation_when_depends_on_absent if {
	violations := compose_depends_on_without_condition.violations with input as _compose({"api": _service({})})
	count(violations) == 0
}

test_no_violation_for_an_empty_depends_on_list if {
	violations := compose_depends_on_without_condition.violations with input as _compose({"api": _service({"depends_on": []})})
	count(violations) == 0
}
