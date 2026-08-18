package greensecops.ci_workflow.maintainability.archived_action_test

import data.greensecops.ci_workflow.maintainability.archived_action
import rego.v1

_uses := "abandoned-org/old-action@8a940392f4c65274539453a5d5a76d9550203ac1"

_workflow(meta) := {
	"jobs": {"build": {"steps": [{"uses": _uses}]}},
	"__actions__": meta,
}

test_violation_when_archived if {
	violations := archived_action.violations with input as _workflow({_uses: {"lookup": "ok", "archived": true}})
	count(violations) == 1
	some v in violations
	v.rule == "archived_action"
	v.category == "maintainability"
}

test_no_violation_when_unenriched if {
	violations := archived_action.violations with input as {"jobs": {"build": {"steps": [{"uses": _uses}]}}}
	count(violations) == 0
}

test_no_violation_when_not_archived if {
	violations := archived_action.violations with input as _workflow({_uses: {"lookup": "ok", "archived": false}})
	count(violations) == 0
}

test_no_violation_when_the_repository_could_not_be_read if {
	violations := archived_action.violations with input as _workflow({_uses: {"lookup": "forbidden", "archived": true}})
	count(violations) == 0
}
