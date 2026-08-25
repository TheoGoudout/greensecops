# Helpers shared by the `iac_ansible` rules.
#
# Lives under `rules/` rather than beside the other services because
# `opa/Dockerfile` copies exactly this directory to the policy server, and a
# helper the server cannot load is a helper no rule can import. `LIB_DIR` in
# `core/rego_metadata.py` keeps everything here out of rule discovery, so this
# file needs no METADATA block and contributes no `Rule` row.
#
# The heavy lifting — resolving which key of a task mapping names the module,
# normalising it to an FQCN, and flattening `block`/`rescue`/`always` — is done
# by `services/ansible/parser.py` before OPA ever sees the document. Rego
# forbids recursive rule definitions, so a nested block cannot be walked here;
# and the task-keyword set that identifies a module by elimination is
# version-dependent, so it belongs in one Python constant rather than in every
# rule. What is left for this file is the small stuff rules repeat.
package greensecops.lib.ansible

import rego.v1

# ─── Document navigation ─────────────────────────────────────────────────────

# The repository path of a file entry, for a violation's `file_path`.
path(file) := object.get(file, "__ansible_file", "")

# Every task in a file, blocks already flattened into the same list. Undefined
# for a file kind that holds no tasks, which is what keeps a `vars` file out of
# a task rule's iteration.
tasks_of(file) := object.get(file, "tasks", [])

# A playbook's plays, without their task lists — those are in `tasks_of`, each
# tagged with `__play_index__`.
plays_of(file) := object.get(file, "plays", [])

# The mapping in a `vars` file, or in a galaxy `requirements.yml`.
vars_of(file) := object.get(file, "vars", {})

requirements_of(file) := object.get(file, "requirements", {})

# ─── Task shape ──────────────────────────────────────────────────────────────

# The task's module, fully qualified: `ansible.builtin.apt`.
module(task) := object.get(task, "__module__", "")

# The trailing segment of the module name: `apt`. Useful when a rule cares
# about the module a collection reimplements under its own namespace.
short_module(task) := last if {
	parts := split(module(task), ".")
	last := parts[count(parts) - 1]
}

# One module argument. Deliberately **undefined** when the argument is absent,
# so a rule can write `not ans.arg(task, "checksum")` and mean it.
arg(task, key) := object.get(task, "__args__", {})[key]

has_arg(task, key) if {
	_ = arg(task, key)
}

# True when the task *writes* a keyword, whatever it wrote. Distinct from
# reading the value: `changed_when: false` is a declaration, and a rule that
# tested `not task.changed_when` would treat it as absent and fire.
declares(task, key) if {
	_ = task[key]
}

# The task's `name:`, or "" when it has none.
name_of(task) := object.get(task, "name", "")

# 1-based source lines, for a violation's span.
line(node) := object.get(node, "__start_line__", null)

end_line(node) := object.get(node, "__end_line__", null)

# What makes two findings of one rule in one file distinct. Never a line
# number: a fingerprint keys on this across scans, so it has to survive an edit
# above the task. The name is the stable identity; the ordinal is only reached
# for an unnamed task, which `task_missing_name` reports anyway.
discriminator(task) := name_of(task) if name_of(task) != ""

discriminator(task) := sprintf("%s#%v", [module(task), object.get(task, "__task_index__", 0)]) if {
	name_of(task) == ""
}

# ─── Values ──────────────────────────────────────────────────────────────────

# True when a value carries a Jinja expression or statement. A templated value
# cannot be judged statically — resolving it would mean following vars across
# group_vars, host_vars, role defaults and set_fact — so rules skip these
# rather than guess. A false positive on a templated value is worse than a miss.
is_templated(value) if {
	is_string(value)
	contains(value, "{{")
}

is_templated(value) if {
	is_string(value)
	contains(value, "{%")
}

# A plain literal: present, a string, and not templated.
literal(value) if {
	is_string(value)
	not is_templated(value)
}

# True when a boolean-ish YAML value means yes. Ansible accepts several
# spellings and ruamel hands back whichever was written.
truthy(value) if value == true

truthy(value) if {
	is_string(value)
	lower(value) in {"yes", "true", "on"}
}

falsy(value) if value == false

falsy(value) if {
	is_string(value)
	lower(value) in {"no", "false", "off"}
}

# ─── Credentials ─────────────────────────────────────────────────────────────

# True when a name denotes a single credential. The singular forms are
# deliberate: `required_secrets` and `api_keys` name *lists of identifiers*, not
# values, and this repository's own group_vars carries exactly such a list. A
# pattern that matched the plural would report it as a leaked credential.
secret_name(name) if {
	is_string(name)
	regex.match(`(?i)(^|_)(password|passwd|secret|token|api_key|apikey|private_key|access_key|secret_key|credential)($|_)`, name)
}

# ─── Command modules ─────────────────────────────────────────────────────────

# The modules that run a command rather than describing state. Grouped because
# four rules key on the same set.
command_modules := {
	"ansible.builtin.command",
	"ansible.builtin.shell",
	"ansible.builtin.raw",
	"ansible.builtin.script",
}

is_command(task) if module(task) in command_modules

# The command line a task runs, whichever way it was written: `shell: cmd`,
# `shell: {cmd: ...}`, or `command: {argv: [...]}`. Undefined when the task
# runs no free-form string — an `argv` list is not shell-interpreted, which is
# exactly why the injection rule must not report it.
command_string(task) := arg(task, "_raw_params")

command_string(task) := arg(task, "cmd") if {
	not has_arg(task, "_raw_params")
}
