# Plan: Per-Process Resource Sampling Binary for the Telemetry Action

**Source**: TODO.md (Feature #2)
**Complexity**: Large (new language toolchain in an otherwise TS/Python repo, cross-compilation, action + backend schema change)

## Summary
`action/src/telemetry.ts` + `daemon.ts` already sample **system-wide** metrics (CPU load, RAM, disk, net) every `INPUT_SAMPLE_INTERVAL` seconds (default 30s) via `/proc/net/dev` and Node's `os` module, POSTing each tick to `/api/v1/telemetry/sample`. This feature adds **per-process** granularity: which processes are actually consuming the resources during a run. Node can't cheaply compute per-process CPU% deltas at this frequency without spawning `ps` repeatedly (slow, not portable, and exactly the kind of thing the TODO asks to move to a real binary instead) — so a small standalone binary reads `/proc/[pid]/{stat,status}` directly, computes CPU%/RAM% per process over a short internal sampling window, keeps the top 5–10% by usage, and prints one JSON line to stdout. `daemon.ts` spawns it synchronously once per existing tick (no second timing loop) and folds the result into the same sample payload it already sends.

## Key Technical Decision: Go, not Rust
Recommended, but reversible if you'd rather use Rust — implementation stays a self-contained binary either way:
- **Go** cross-compiles to static Linux binaries with zero toolchain ceremony: `CGO_ENABLED=0 GOOS=linux GOARCH={386,amd64,arm64} go build` — no musl target juggling, no libc linking concerns, matches "no/little external lib dependencies" directly.
- Rust would need `rustup target add {i686,x86_64,aarch64}-unknown-linux-musl` plus a musl cross-linker per arch to get equivalent static binaries — more CI toil for the same result.
- All we need is reading a handful of text files under `/proc` and doing arithmetic — no unsafe code, no perf-critical inner loop that would favor Rust here.

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| /proc reading, "not fatal" fallback | `action/src/telemetry.ts:79-96` | Wrap `/proc` reads in try/catch, degrade gracefully (system telemetry already treats `/proc/net/dev` absence as non-fatal on non-Linux) |
| Daemon tick loop | `action/src/daemon.ts:35-50` | `tick()` swallows all errors — "daemon must never crash the runner"; the new binary's spawn must follow the exact same swallow-and-continue contract |
| Sample payload shape | `action/src/types.ts:13-23` (`MetricsSample`), `action/src/daemon.ts:39-46` (`sendSample` call site) | New field added the same way `disk_used_gb`/`net_bytes_sent` were: optional, additive, no breaking change to existing consumers |
| Backend ingestion schema | `backend/app/api/routes/telemetry.py:47-53` (`SamplePayload`) | Same flat `BaseModel` with `| None = None` optional fields |
| Backend flat metrics table | `backend/app/models/db.py:480-494` (`TelemetryMetricSample`) | New nullable column, same style as existing `cpu_percent`/`ram_used_mb` |
| Migration format | `backend/app/alembic/versions/0037_issue_needs_manual_work.py` | Numbered revision, docstring explaining *why*, `op.add_column(..., nullable=True)` — additive, no backfill needed |
| Action test style | `action/src/__tests__/telemetry.test.ts` | `bun test`, mocks `fs`/`child_process`, asserts on the parsed shape not exact byte output |
| Cross-compile CI | *(none exists yet — this is the first non-TS/Python toolchain in the repo)* | State explicitly: no existing pattern to mirror; new `.github/workflows` job modeled on `test-action.yml`'s structure (path-filtered, SHA-pinned actions) |

## Files to Change
| File | Action | Why |
|---|---|---|
| `action/native/proc-sampler/main.go` | CREATE | The binary: enumerate `/proc/[0-9]+`, compute CPU%/RSS over a short internal window, keep top 5–10%, print JSON to stdout |
| `action/native/proc-sampler/main_test.go` | CREATE | Unit tests for the parsing/ranking logic against fixture `/proc`-shaped strings (not real `/proc` — CI runners' process tables aren't controllable) |
| `action/native/proc-sampler/go.mod` | CREATE | Standalone Go module, zero external dependencies (stdlib only: `os`, `strconv`, `sort`, `encoding/json`) |
| `action/src/native.ts` | CREATE | `getTopProcesses(): Promise<TopProcess[] \| null>` — resolves the right prebuilt binary for `process.arch`, spawns it with a timeout, parses stdout JSON, returns `null` (not throw) on any failure |
| `action/src/types.ts` | UPDATE | Add `TopProcess[]` type and `top_processes?: TopProcess[]` to `MetricsSample` |
| `action/src/daemon.ts` | UPDATE | `tick()` calls `getTopProcesses()` alongside `getMetricsSample()`, includes result in the `sendSample` call |
| `action/package.json` | UPDATE | `build` script gains a step that copies the 3 prebuilt binaries into `dist/bin/` after the existing `ncc build` calls (ncc only bundles JS — binaries are separate assets) |
| `.github/workflows/build-proc-sampler.yml` | CREATE | New root workflow: cross-compile the Go binary for `linux/{386,amd64,arm64}` on every `action/native/**` change, upload as artifacts consumed by the existing action CI/build |
| `backend/app/api/routes/telemetry.py` | UPDATE | `SamplePayload` gains `top_processes: list[dict] \| None = None`; `ingest_sample` passes it through |
| `backend/app/models/db.py` | UPDATE | `TelemetryMetricSample` gains `top_processes: str \| None` (JSON-encoded text, same convention as `TelemetryRun.metrics`) |
| `backend/app/alembic/versions/0039_telemetry_metric_sample_top_processes.py` | CREATE | `op.add_column("telemetry_metric_sample", sa.Column("top_processes", sa.Text(), nullable=True))` |
| `backend/tests/api/routes/test_telemetry.py` | UPDATE | Cover `top_processes` accepted, stored, and omitted-gracefully when absent |

## Tasks

### Task 1: `proc-sampler` binary — core sampling logic
- **Action**: For each numeric entry in `/proc`, read `/proc/[pid]/stat` (fields `utime`+`stime`, ticks since boot) and `/proc/[pid]/status` (`VmRSS` line) plus `/proc/[pid]/comm` (process name). Take two full passes ~200ms apart (matches the standard `top`-style delta technique — a single `/proc/[pid]/stat` read only gives *cumulative* ticks since process start, not instantaneous load), compute `cpu_percent = (Δutime+Δstime) / (Δrealtime_ticks × ncpu) × 100` per pid, and `mem_percent` from `VmRSS / MemTotal` (`/proc/meminfo`).
- **Mirror**: no existing Go code in the repo — follow stdlib-only, no third-party deps, matching the "little external lib dependencies" requirement directly rather than approximating it.
- **Validate**: `go test ./...` inside `action/native/proc-sampler`

### Task 2: Ranking + output contract
- **Action**: Sort processes by `cpu_percent` descending (tiebreak `mem_percent`), keep `ceil(N × 0.10)` with a floor of 5 and a cap of 20 (bounds payload size on both near-empty and very busy runners — CI boxes commonly have 20-150 processes, so a flat "top 10%" alone would return 2 processes on a quiet box or 15 on a busy one; the floor/cap keeps the signal useful either way). Print a single JSON array `[{pid, name, cpu_percent, mem_percent, mem_rss_mb}, ...]` to stdout, nothing else (no logging to stdout — only stderr on error, matching Unix tool conventions so the TS side can trust "stdout is exactly the payload").
- **Mirror**: `action/src/telemetry.ts`'s rounding conventions (`Math.round(x * 10) / 10`-style precision) — replicate in Go for consistent precision across the two languages.
- **Validate**: `main_test.go` asserts the floor/cap math against synthetic process counts (3, 20, 200)

### Task 3: `action/src/native.ts` — spawn + parse from TypeScript
- **Action**: Map `process.arch` (`'x64' → 'amd64'`, `'arm64' → 'arm64'`, `'ia32' → '386'`) to the matching prebuilt binary under `dist/bin/`. Spawn with `child_process.execFileSync`, a hard timeout (e.g. 2000ms — the binary's own internal 200ms window plus generous margin), `platform !== 'linux'` short-circuits to `null` immediately (mirrors `readDiskKb`'s `df`-may-not-exist tolerance, but explicit here since the binary is Linux-only by design per the TODO). Any spawn/parse failure → `null`, never throws.
- **Mirror**: `action/src/telemetry.ts:7-26` (`readDiskKb`)'s try/catch-returns-null shape
- **Validate**: `bun test action/src/__tests__/native.test.ts` — mock `child_process.execFileSync` to return valid JSON, invalid JSON, and a thrown error; assert `null` only in the latter two

### Task 4: Wire into the daemon + payload types
- **Action**: `types.ts`: add `TopProcess { pid: number; name: string; cpu_percent: number; mem_percent: number; mem_rss_mb: number }` and `top_processes?: TopProcess[]` on `MetricsSample`. `daemon.ts`'s `tick()`: `const topProcesses = await getTopProcesses()`, include in the `sendSample` call only when non-null (keep the payload additive/optional, same as every other field here).
- **Mirror**: `action/src/daemon.ts:38-46`
- **Validate**: `bun test` (existing `daemon` coverage, extended)

### Task 5: Bundle the binaries into `dist/`
- **Action**: `package.json`'s `build` script, after the four existing `ncc build` calls, adds `mkdir -p dist/bin && cp native/proc-sampler/build/proc-sampler-linux-{386,amd64,arm64} dist/bin/` (binaries produced by Task 6's CI job land in that path before `bun run build` runs). Document in `action/README.md` that `dist/bin/*` are committed prebuilt binaries, same rationale as `dist/{pre,main,post}` already being committed despite `dist` being gitignored during local dev.
- **Mirror**: `action/package.json:6` (existing multi-`ncc`-call build script)
- **Validate**: `ls action/dist/bin/` shows all 3 binaries after a full `bun run build`

### Task 6: Cross-compile CI job
- **Action**: New `.github/workflows/build-proc-sampler.yml`, path-filtered to `action/native/**`, matrix over `{386, amd64, arm64}`, each leg: `cd action/native/proc-sampler && CGO_ENABLED=0 GOOS=linux GOARCH=${{ matrix.arch }} go build -o build/proc-sampler-linux-${{ matrix.arch }} .`, upload as a build artifact; the existing action CI (`test-action.yml` today, `action/.github/workflows/ci.yml` once extracted per the standalone-repo plan) downloads these artifacts before running `bun run build` so Task 5's copy step has something to copy.
- **Mirror**: `.github/workflows/test-action.yml`'s path-filter + SHA-pinned-actions structure; run `uvx zizmor` against the new workflow before considering it done, same as `sync-action-repo.yml` in the prior plan.
- **Validate**: `gh run view` on a PR touching `action/native/**` shows 3 successful matrix legs + artifacts

### Task 7: Backend — accept and store `top_processes`
- **Action**: `SamplePayload.top_processes: list[dict[str, Any]] | None = None`; `ingest_sample` passes `json.dumps(payload.top_processes) if payload.top_processes else None` into `TelemetryMetricSample.top_processes`. Alembic migration adds the nullable `Text` column (additive, no backfill, no default needed beyond `NULL`).
- **Mirror**: `backend/app/alembic/versions/0037_issue_needs_manual_work.py`'s docstring-explains-why convention; `backend/app/api/routes/telemetry.py:133-138` (existing `TelemetryMetricSample(...)` construction)
- **Validate**: `pytest backend/tests/api/routes/test_telemetry.py -q`

## Validation
```bash
cd action/native/proc-sampler && go test ./... && go vet ./...
cd action && bun test && bun run typecheck && bun run lint
cd backend && source ../.venv/bin/activate && python3 -m pytest tests/api/routes/test_telemetry.py -q
uvx zizmor .github/workflows/build-proc-sampler.yml
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| `/proc` read races (pid exits between the two sampling passes) | Medium | Treat a missing pid on the second pass as "skip this pid", not a fatal error — very common on a busy CI box |
| Binary missing/wrong-arch on an exotic runner | Low | `getTopProcesses()` returns `null` on any spawn failure; daemon already tolerates optional fields being absent |
| Payload size growth (20 processes × ~5 fields per tick, every 30s) | Low | Floor/cap (5–20) bounds this; still far smaller than the workflow YAML content already stored per analysis |
| New Go toolchain adds a CI dependency the team doesn't otherwise maintain | Medium | Stdlib-only, no deps to patch/audit; a single `go.mod` with no third-party packages minimizes ongoing maintenance surface |
| `top_processes` column growth on `telemetry_metric_sample` (one row per 30s tick, unbounded run duration) | Low-Medium | Existing table already grows unbounded per tick today (that's its whole design); no new retention policy introduced by this change specifically — flag as a pre-existing consideration, not a regression |

## Acceptance
- [ ] `proc-sampler` compiles for linux/386, linux/amd64, linux/arm64 with `CGO_ENABLED=0`
- [ ] Binary output is valid JSON, top 5–10% (floor 5, cap 20) by CPU%, no stdout noise
- [ ] `daemon.ts` includes `top_processes` in each sample tick without disrupting existing fields, and never crashes the runner if the binary is missing/fails
- [ ] Backend accepts, stores, and gracefully omits `top_processes`
- [ ] All new/changed tests pass; zizmor clean on the new workflow
