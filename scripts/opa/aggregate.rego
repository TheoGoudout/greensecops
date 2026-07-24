# Aggregates the `violations` set from every
# greensecops.<domain>.<category>.<rule> package into one set, so a workflow
# can be evaluated against the whole rule suite in a single query
# (data.aggregate.all_violations).
#
# Kept OUTSIDE backend/app/rules so it is never shipped to the OPA policy
# server — it exists only for scripts/validate_examples.py and CI.
package aggregate

import rego.v1

all_violations contains out if {
	some domain, category, rule
	v := data.greensecops[domain][category][rule].violations[_]
	out := {
		"rule": v.rule,
		"severity": v.severity,
		"category": v.category,
		"message": v.message,
	}
}
