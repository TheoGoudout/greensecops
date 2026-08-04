# Real-world Terraform fixtures

Terraform vendored **verbatim** from public repositories, so the backend's
Terraform tests run against configuration people actually wrote rather than
snippets invented for the test. This is the Terraform counterpart to
[`../workflows/`](../workflows), which vendors real CI workflows from
encode/httpx, celery/celery and redis/redis-py for the workflow engine's tests.

Consumed by:

- [`tests/workers/tasks/test_terraform_analysis_integration.py`](../../workers/tasks/test_terraform_analysis_integration.py)
  — parse/merge assertions plus the full scan pipeline, per case.
- [`tests/services/test_hcl_parser.py`](../../services/test_hcl_parser.py) —
  `parse_terraform_content` / `merge_terraform_configs` / `derive_module_path`.
- [`tests/workers/tasks/test_terraform_fix_generation.py`](../../workers/tasks/test_terraform_fix_generation.py)
  — the vulnerable file an LLM fix is generated against.
- [`tests/api/routes/test_terraform.py`](../../api/routes/test_terraform.py) —
  the `GET /terraform-roots/{id}/files` payload.

Each case directory is one Terraform **root module** — several `.tf` files that
`merge_terraform_configs` folds into a single config, exactly as production
treats a directory. That multi-file shape is the point: it is what exercises
`__tf_file` source tagging, cross-file block concatenation and per-file line
spans.

## Cases

| Directory | Vendored from | What it anchors |
| --- | --- | --- |
| `terragoat_aws/` | [bridgecrewio/terragoat](https://github.com/bridgecrewio/terragoat) `terraform/aws/` (Apache-2.0) | The violation side. Bridgecrew's deliberately-insecure-but-realistic AWS estate: a security group open to `0.0.0.0/0` on both 22 and 80, an unencrypted EBS volume, three unversioned S3 buckets, an unencrypted RDS instance, and AWS keys baked into `user_data` and a Lambda's environment. Full of `merge()`, interpolation, heredocs, `depends_on` and a 170-line `aws_instance`. |
| `terraform_aws_security_group/` | [terraform-aws-modules/terraform-aws-security-group](https://github.com/terraform-aws-modules/terraform-aws-security-group) (Apache-2.0) | The clean side, and the parser's stress test. One of the most-downloaded modules in the registry, built entirely out of `for_each` comprehensions, `dynamic` blocks, `try()`, `coalesce()`, `merge()` and `variable` blocks carrying `validation`. Trips nothing — a false-positive guard on hardened production code. |
| `terraform_aws_vpc_complete/` | [terraform-aws-modules/terraform-aws-vpc](https://github.com/terraform-aws-modules/terraform-aws-vpc) `examples/complete/` (Apache-2.0) | Module-composition style: `module`, `locals`, `data`, `provider` and `terraform` blocks with only one raw resource. Exercises the one-level branch of `_tag_source_file` (everything that is not `resource`/`data`) on real code. Also trips nothing. |

Exact commits are recorded per case in `expected.json` under `source.ref`. The
`.tf` files are byte-for-byte upstream — no headers added, no reformatting — so
they stay a truthful anchor. Attribution and licence live here rather than in
the files themselves.

**One documented exception.** `terragoat_aws/ec2.tf` lines 15-16 carry
terragoat's own fake credential pair, which GitHub's push protection rejects.
They are replaced with AWS's published documentation placeholders
(`AKIAIOSFODNN7EXAMPLE` / `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`) — the same
strings `examples/terraform/aws-ec2-web/main.tf` already uses, and the same
length, so no line or column shifts. `hardcoded_credentials_in_tf` still fires
on `aws_instance.web_host` exactly as it does upstream. Nothing else in the
corpus is modified; re-vendoring any other file must stay verbatim.

Two of the three cases being violation-free is not an accident of selection:
well-maintained public modules are clean under this rule suite, and proving the
rules stay quiet on them is as valuable as proving they fire on terragoat.

## `expected.json`

Generated, not hand-written. [`scripts/regenerate_terraform_fixtures.py`](../../../../scripts/regenerate_terraform_fixtures.py)
runs the real `iac_terraform` rule suite over each case through the production
parse/merge path and records what it finds:

```jsonc
{
  "source":   { "repository": …, "path": …, "ref": …, "license": … },
  "files":    ["db-app.tf", "ec2.tf", …],
  "violations": [ { "rule_slug": …, "severity": …, "category": …, "message": …,
                    "resource_address": …, "file_path": …, "line_start": …, "line_end": … } ],
  "expected_finding_count": 8,
  "expected_grade": null            // "A+++" when the case is clean
}
```

`expected_finding_count` is **not** `len(violations)`: a `TerraformFinding`'s
fingerprint (`app/services/deduplication.py`) keys on
`(root, rule, resource_address)`, so terragoat's security group — open on port
22 *and* port 80, two violations of one rule on one resource — collapses into a
single finding. Real code producing that collapse is exactly why the corpus is
worth having.

The backend test environment has no `opa` binary, so the tests replay these
recorded violations through a mocked `_evaluate` (the same arrangement
`test_static_analysis_integration.py` uses). The parse, merge, tagging,
fingerprinting, persistence and scoring around it are all real.

## Adding a case

1. Create a directory here named for the source, and drop in the `.tf` /
   `.tf.json` files **verbatim** from a permissively-licensed public repo.
2. Add the case to `SOURCES` in `scripts/regenerate_terraform_fixtures.py`
   (repository, path, ref, licence) and add a row to the table above.
3. Regenerate, with `opa` on `PATH` or `OPA_BIN` set:

   ```bash
   python scripts/regenerate_terraform_fixtures.py
   ```

`test_terraform_analysis_integration.py` discovers every directory holding an
`expected.json` automatically — no test code changes needed.

Re-run the same command after changing a rule under
`backend/app/rules/iac_terraform/`, and review the diff: it shows precisely how
the change lands on real-world Terraform.
