package greensecops.container_docker.energy.copy_before_dependency_install_test

import data.greensecops.container_docker.energy.copy_before_dependency_install
import rego.v1

_inst(keyword, value, stage, line) := {
	"instruction": keyword,
	"value": value,
	"flags": {},
	"heredoc": null,
	"stage": stage,
	"__start_line__": line,
	"__end_line__": line,
}

_df(stages, instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": stages[count(stages) - 1].index,
	"stages": stages,
	"instructions": instructions,
}]}

_stage(index, name) := {"index": index, "name": name, "is_final": true, "__start_line__": 1, "__end_line__": 9}

test_violation_when_copy_all_precedes_npm_ci if {
	violations := copy_before_dependency_install.violations with input as _df(
		[_stage(0, null)],
		[
			_inst("COPY", ". .", 0, 3),
			_inst("RUN", "npm ci", 0, 4),
		],
	)
	count(violations) == 1
	some v in violations
	v.line_start == 3
	v.line_end == 4
}

test_no_violation_when_manifests_are_copied_first if {
	violations := copy_before_dependency_install.violations with input as _df(
		[_stage(0, null)],
		[
			_inst("COPY", "package.json package-lock.json ./", 0, 3),
			_inst("RUN", "npm ci", 0, 4),
			_inst("COPY", ". .", 0, 5),
		],
	)
	count(violations) == 0
}

test_no_violation_without_a_dependency_install if {
	violations := copy_before_dependency_install.violations with input as _df(
		[_stage(0, null)],
		[_inst("COPY", ". .", 0, 3)],
	)
	count(violations) == 0
}

# `COPY --from=builder` reads an earlier stage, not the build context.
test_no_violation_for_copy_from_another_stage if {
	violations := copy_before_dependency_install.violations with input as _df(
		[_stage(0, null)],
		[
			object.union(_inst("COPY", ". /app", 0, 3), {"flags": {"from": "builder"}}),
			_inst("RUN", "npm ci", 0, 4),
		],
	)
	count(violations) == 0
}

test_violation_for_pip_install if {
	violations := copy_before_dependency_install.violations with input as _df(
		[_stage(0, null)],
		[
			_inst("COPY", ". .", 0, 3),
			_inst("RUN", "pip install -r requirements.txt", 0, 4),
		],
	)
	count(violations) == 1
}

# Each stage is judged on its own ordering.
test_violation_scoped_to_the_offending_stage if {
	violations := copy_before_dependency_install.violations with input as _df(
		[
			{"index": 0, "name": "builder", "is_final": false, "__start_line__": 1, "__end_line__": 5},
			{"index": 1, "name": null, "is_final": true, "__start_line__": 6, "__end_line__": 9},
		],
		[
			_inst("COPY", "go.mod go.sum ./", 0, 2),
			_inst("RUN", "go mod download", 0, 3),
			_inst("COPY", ". .", 1, 7),
			_inst("RUN", "npm ci", 1, 8),
		],
	)
	count(violations) == 1
	some v in violations
	v.discriminator == "stage:1"
}
