# Plan: GreenSecOps — CI/CD Intelligence Platform

**Complexity**: Large  
**Stack**: FastAPI + SQLModel + PostgreSQL + Celery + Redis + React + TypeScript + Vite + Tailwind + shadcn/ui + OPA + LangChain + LangSmith + Docker Compose + Traefik

---

## Summary

GreenSecOps analyzes GitHub CI/CD pipelines across five axes (energy, reliability, security, performance, maintainability) using static analysis (GitHub App + Rego/OPA) and optional dynamic telemetry (embedded GitHub Action). When violations are found, an LLM-agnostic fix engine auto-generates and delivers fixes as PRs or comments. Content-hash deduplication prevents re-analyzing identical workflows.

---

## Brand Identity

| Token | Value | Usage |
|---|---|---|
| Primary | `#1A7A4A` (forest green) | Logo, CTAs, primary buttons |
| Accent | `#0EA5E9` (electric blue) | Links, highlights, code |
| Warning | `#F59E0B` (amber) | Medium severity issues |
| Critical | `#EF4444` (red) | Critical/blocking issues |
| Success | `#10B981` (emerald) | Passing checks, A ratings |
| Dark BG | `#0F172A` (slate-900) | Dark mode background |
| Light BG | `#F8FAFC` (slate-50) | Light mode background |

Logo concept: circuit-board leaf (green sustainability meets DevOps tech).

---

## Pricing Tiers

| Tier | Price | Repos | Analyses/mo | LLM Fixes/mo | Custom Rules | LLM Config |
|---|---|---|---|---|---|---|
| **Free** | $0 | 3 | 50 | 5 | ✗ | Global default only |
| **Starter** | $9/mo | 10 | 500 | 50 | ✗ | Org/repo override |
| **Pro** | $49/mo | Unlimited | Unlimited | 500 | ✓ | Full catalog |
| **Ultimate** | Custom | Unlimited | Unlimited | Unlimited | ✓ + Marketplace | On-prem, SLA |
| **Open Source** | $0 | 5 public | Unlimited | 20 | ✗ | Global default |

Open Source tier: verified by repo public visibility + OSS license detection.  
Badge system available on all tiers.

---

## Rating System (Badges)

Scores 0–100 computed from weighted violations:

| Grade | Score | Badge color |
|---|---|---|
| A+++ | 98–100 | `#10B981` |
| A++ | 95–97 | `#22C55E` |
| A+ | 90–94 | `#84CC16` |
| A | 85–89 | `#A3E635` |
| B | 70–84 | `#F59E0B` |
| C | 55–69 | `#FB923C` |
| D | 40–54 | `#EF4444` |
| F | 0–39 | `#991B1B` |

Badges issued per repo + per branch. SVG endpoint: `/badges/{owner}/{repo}/{branch}.svg`

---

## Rego Rule Categories & Initial Rules

### 1. Energy Efficiency (`energy/`)
- `runner_sizing` — flags oversized runners for trivial jobs (lint, test)
- `caching_missing` — detects absent package manager caches (pip, npm, gradle, cargo)
- `redundant_steps` — identical steps across jobs without reuse
- `artifact_reuse` — build artifacts not reused across dependent jobs
- `parallel_opportunity` — sequential jobs with no dependency chain
- `large_runner_justification` — GPU/large runners without resource-intensive steps

### 2. Reliability (`reliability/`)
- `missing_timeout` — jobs/steps without timeout-minutes
- `missing_retry` — flaky network steps without retry logic
- `unpinned_actions` — uses `@main` or `@v1` instead of SHA pin
- `missing_concurrency` — no concurrency group on PR workflows (duplicate runs)
- `artifact_retention` — no explicit retention days on uploaded artifacts
- `no_continue_on_error_abuse` — `continue-on-error: true` masking real failures

### 3. Security (`security/`)
- `excessive_token_permissions` — `permissions: write-all` or missing explicit scopes
- `hardcoded_secrets` — env vars with names matching secret patterns
- `untrusted_actions` — third-party actions not pinned to SHA
- `pr_target_injection` — `pull_request_target` with checkout of PR head
- `oidc_not_used` — long-lived cloud credentials instead of OIDC
- `world_writable_artifact` — artifacts uploaded without access control

### 4. Performance (`performance/`)
- `cache_key_too_broad` — cache keys that never miss (defeating the purpose)
- `slow_setup_order` — expensive steps before fast-fail checks
- `no_matrix_strategy` — repeated nearly-identical jobs without matrix
- `unnecessary_full_checkout` — `fetch-depth: 0` when not needed

### 5. Maintainability (`maintainability/`)
- `no_reusable_workflow` — copy-pasted workflow blocks across files
- `workflow_too_complex` — step count > threshold without reusable workflows
- `missing_workflow_description` — no `name` on jobs/steps
- `hardcoded_env_values` — values that should be in vars/secrets

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Frontend (React + Vite)                      │
│   Dashboard │ Repos │ Issues │ Rules │ Badges │ Settings │ Billing│
└─────────────────────────────┬────────────────────────────────────┘
                              │ HTTPS
┌─────────────────────────────▼────────────────────────────────────┐
│                      Traefik (TLS termination)                   │
└──────────┬──────────────────┬───────────────────────────────────-┘
           │                  │
   ┌───────▼──────┐  ┌────────▼──────────┐
   │  FastAPI API │  │  Webhook Handler  │
   │  (auth/CRUD) │  │  (GitHub events)  │
   └───────┬──────┘  └────────┬──────────┘
           │                  │
┌──────────▼──────────────────▼──────────────────────────────────-┐
│                    Redis (broker + cache + dedup)                │
└──────────┬──────────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────┐
│                        Celery Workers                            │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │Static Anlyz  │  │Dynamic Anlyz │  │ LLM Fix Engine         │ │
│  │(OPA + Rego)  │  │(Telemetry)   │  │(LangChain + LangSmith) │ │
│  └──────────────┘  └──────────────┘  └────────────────────────┘ │
└──────────┬──────────────────────────────────────────────────────┘
           │
┌──────────▼────────────┐   ┌──────────────────────────────────────┐
│      PostgreSQL        │   │           GitHub App                 │
│  (all persistent data) │   │  (OAuth, webhooks, fetch, PR/comment)│
└───────────────────────┘   └──────────────────────────────────────┘
```

---

## Repository Structure

```
greensecops/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py                    # auth/db deps
│   │   │   └── routes/
│   │   │       ├── auth.py                # JWT + GitHub OAuth
│   │   │       ├── users.py
│   │   │       ├── organizations.py
│   │   │       ├── repositories.py
│   │   │       ├── analyses.py
│   │   │       ├── issues.py
│   │   │       ├── fixes.py
│   │   │       ├── rules.py
│   │   │       ├── webhooks.py            # GitHub webhook receiver
│   │   │       ├── telemetry.py           # Action telemetry ingestion
│   │   │       ├── badges.py              # SVG badge generation
│   │   │       └── billing.py
│   │   ├── core/
│   │   │   ├── config.py                  # Pydantic settings
│   │   │   ├── security.py                # JWT, hashing
│   │   │   └── db.py                      # SQLModel engine
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   ├── organization.py
│   │   │   ├── repository.py
│   │   │   ├── analysis.py                # has content_hash for dedup
│   │   │   ├── workflow_file.py           # cached fetched workflow YAML
│   │   │   ├── issue.py
│   │   │   ├── fix.py
│   │   │   ├── rule.py
│   │   │   ├── telemetry_run.py
│   │   │   └── billing.py
│   │   ├── workers/
│   │   │   ├── celery_app.py
│   │   │   └── tasks/
│   │   │       ├── static_analysis.py
│   │   │       ├── dynamic_analysis.py
│   │   │       ├── fix_generation.py
│   │   │       └── fix_delivery.py
│   │   ├── services/
│   │   │   ├── github/
│   │   │   │   ├── app_client.py          # GitHub App auth + API
│   │   │   │   ├── webhook_verifier.py
│   │   │   │   └── fix_delivery.py        # PR creation / comment
│   │   │   ├── opa/
│   │   │   │   ├── evaluator.py           # OPA REST sidecar client
│   │   │   │   └── result_parser.py
│   │   │   ├── deduplication.py           # SHA256 content hash logic
│   │   │   ├── badge_renderer.py          # SVG generation
│   │   │   ├── scoring.py                 # 0-100 score + grade
│   │   │   └── llm/
│   │   │       ├── base.py                # abstract provider
│   │   │       ├── catalog.py             # provider registry
│   │   │       ├── providers/
│   │   │       │   ├── openai_provider.py
│   │   │       │   ├── anthropic_provider.py
│   │   │       │   ├── gemini_provider.py
│   │   │       │   └── ollama_provider.py
│   │   │       └── fix_prompt.py          # prompt templates per rule
│   │   └── rules/
│   │       ├── energy/
│   │       │   ├── runner_sizing.rego
│   │       │   ├── caching_missing.rego
│   │       │   ├── redundant_steps.rego
│   │       │   ├── artifact_reuse.rego
│   │       │   └── parallel_opportunity.rego
│   │       ├── reliability/
│   │       │   ├── missing_timeout.rego
│   │       │   ├── unpinned_actions.rego
│   │       │   ├── missing_concurrency.rego
│   │       │   └── artifact_retention.rego
│   │       ├── security/
│   │       │   ├── excessive_token_permissions.rego
│   │       │   ├── hardcoded_secrets.rego
│   │       │   ├── untrusted_actions.rego
│   │       │   └── pr_target_injection.rego
│   │       ├── performance/
│   │       │   ├── cache_key_too_broad.rego
│   │       │   └── unnecessary_full_checkout.rego
│   │       └── maintainability/
│   │           ├── no_reusable_workflow.rego
│   │           └── hardcoded_env_values.rego
│   ├── tests/
│   │   ├── api/
│   │   ├── services/
│   │   ├── workers/
│   │   └── rules/
│   ├── alembic/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ui/                        # shadcn/ui
│   │   │   ├── layout/
│   │   │   ├── repos/
│   │   │   ├── analysis/
│   │   │   ├── issues/
│   │   │   ├── badges/
│   │   │   └── billing/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Repositories.tsx
│   │   │   ├── AnalysisDetail.tsx
│   │   │   ├── Issues.tsx
│   │   │   ├── Rules.tsx
│   │   │   ├── Badges.tsx
│   │   │   ├── Settings.tsx
│   │   │   └── Billing.tsx
│   │   ├── hooks/
│   │   ├── lib/
│   │   │   └── api-client.ts              # auto-generated from OpenAPI
│   │   └── styles/
│   │       └── greensecops-theme.css
│   ├── e2e/
│   │   └── playwright/
│   ├── package.json
│   └── Dockerfile
├── action/                                # Embeddable GitHub Action
│   ├── action.yml
│   ├── src/
│   │   └── collect_telemetry.py
│   └── README.md
├── docker-compose.yml
├── docker-compose.override.yml
├── .env.example
├── traefik/
│   └── traefik.yml
└── scripts/
    ├── generate-client.sh
    └── seed-rules.sh
```

---

## Database Schema (Key Tables)

```sql
users               (id, email, username, hashed_password, github_id, tier, created_at)
organizations       (id, github_org_id, name, tier, llm_config, fix_delivery_config)
org_members         (org_id, user_id, role)
repositories        (id, org_id, github_repo_id, full_name, install_id, enabled, badge_branch)
workflow_files      (id, repo_id, path, content_hash, raw_content, fetched_at)
analyses            (id, repo_id, workflow_file_id, content_hash, status, score, grade, triggered_by, created_at)
issues              (id, analysis_id, rule_id, severity, category, line_start, line_end, message, context)
fixes               (id, issue_id, llm_provider, prompt_tokens, status, diff, pr_url, comment_url, created_at)
rules               (id, slug, category, severity, title, description, enabled)
telemetry_runs      (id, repo_id, workflow_run_id, runner_specs, metrics_json, collected_at)
billing_subs        (id, user_id, tier, stripe_sub_id, analyses_used, fixes_used, period_start)
```

---

## Implementation Phases

### Phase 0: Foundation (Week 1)
Clone and adapt `fastapi/greensecops` as skeleton.

**Tasks:**
- [ ] Clone template, rename to greensecops
- [ ] Update brand colors in Tailwind config + CSS variables
- [ ] Configure Docker Compose services: api, worker, redis, postgres, traefik, mailcatcher, flower
- [ ] Scaffold SQLModel models (all tables above)
- [ ] Alembic initial migration
- [ ] Extend auth to support GitHub OAuth via GitHub App (alongside username/password)
- [ ] Add user tier field + org/membership models
- [ ] Basic CI pipeline (GitHub Actions for the project itself)

**Validate:** `docker compose up` → all services healthy, `/docs` reachable, login works.

---

### Phase 1: GitHub App Integration (Week 2)
Build the GitHub App client and webhook handler.

**Tasks:**
- [ ] Register GitHub App (permissions: contents:read, workflows:read, pull_requests:write, checks:write)
- [ ] `app/services/github/app_client.py` — JWT auth, installation token refresh, API wrappers
- [ ] `app/services/github/webhook_verifier.py` — HMAC-SHA256 signature verification
- [ ] Webhook route handling events: `workflow_run`, `push` (filter `.github/workflows/**`), `issue_comment` (fix feedback)
- [ ] Repository installation flow (user adds GreenSecOps to repo)
- [ ] Fetch workflow files from repo, store as `WorkflowFile` with content hash
- [ ] `app/services/deduplication.py` — skip analysis if hash already analyzed

**Validate:** Webhook delivery in GitHub App settings shows 200s, workflow files stored in DB.

---

### Phase 2: Static Analysis Engine (Week 3)
OPA + Rego rules evaluation pipeline.

**Tasks:**
- [ ] Add OPA to Docker Compose (REST API sidecar mode)
- [ ] `app/services/opa/evaluator.py` — parse YAML → JSON, call OPA, collect violations
- [ ] Write first 5 Rego rules with unit tests (one per category)
- [ ] `app/services/scoring.py` — weighted score → 0-100 → grade (A+++ to F)
- [ ] Celery task `tasks/static_analysis.py` — triggered by webhook or manual request
- [ ] Store `Analysis` + `Issue` records per run
- [ ] Analyses API routes (CRUD, filter by repo/branch/grade)

**Validate:** POST a test workflow YAML → analysis created → issues populated with correct violations.

---

### Phase 3: LLM Fix Engine (Week 4)
LLM-agnostic fix generation + LangSmith tracing.

**Tasks:**
- [ ] `app/services/llm/base.py` — abstract `LLMProvider` interface
- [ ] Implement 4 providers: OpenAI, Anthropic, Gemini, Ollama
- [ ] `app/services/llm/catalog.py` — load provider from config (env var → org override → repo override)
- [ ] `app/services/llm/fix_prompt.py` — prompt templates per rule category
- [ ] LangSmith tracing integration (wrap all LLM calls)
- [ ] Celery task `tasks/fix_generation.py` — for each `Issue`, call LLM, parse diff, store `Fix`
- [ ] `app/services/github/fix_delivery.py` — create PR or post comment (per repo config)
- [ ] Celery task `tasks/fix_delivery.py`
- [ ] Rate limiting: enforce per-tier fix quotas

**Validate:** Issue created → fix generated → PR opened on test repo → LangSmith trace visible.

---

### Phase 4: Dynamic Telemetry (Week 5)
Embeddable GitHub Action + ingestion pipeline.

**Tasks:**
- [ ] `action/action.yml` — composite action collecting: runner specs, CPU/RAM/disk/net I/O, step timing, binary sys/user time
- [ ] `action/src/collect_telemetry.py` — collects metrics, sends HTTPS POST to telemetry endpoint
- [ ] `app/api/routes/telemetry.py` — authenticated ingestion endpoint, stores `TelemetryRun`
- [ ] Dynamic analysis Celery task — correlate telemetry with static analysis, enrich issues with runtime data
- [ ] Additional Rego rules that use telemetry data (e.g., actual CPU idle → runner oversized)

**Validate:** Add action to test repo → telemetry received → dynamic analysis enriches existing issues.

---

### Phase 5: Frontend Dashboard (Week 6–7)
Full React frontend wired to the API.

**Tasks:**
- [ ] Apply GreenSecOps theme (brand colors, dark mode CSS variables)
- [ ] Generate API client from OpenAPI spec
- [ ] Dashboard: summary stats, recent analyses, grade distribution chart
- [ ] Repositories page: list, add via GitHub App install, per-repo grade badge
- [ ] Analysis detail: workflow file viewer with inline issue annotations, score breakdown
- [ ] Issues page: filter by category/severity, inline fix preview, approve/reject fix
- [ ] Settings: LLM provider config, fix delivery config, per-repo overrides
- [ ] Billing page: tier display, usage meters, upgrade CTA
- [ ] E2E tests (Playwright): install repo → analyze → review issue → approve fix

**Validate:** Full golden path passes in Playwright.

---

### Phase 6: Badges & Public API (Week 8)

**Tasks:**
- [ ] `app/api/routes/badges.py` — SVG badge endpoint (unauthenticated, cache-controlled)
- [ ] `app/services/badge_renderer.py` — generate SVG with grade + color
- [ ] Badge per-branch support (default: main/master)
- [ ] Shields.io-compatible JSON endpoint
- [ ] Badge page in frontend (preview + copy snippet)

**Validate:** `GET /badges/owner/repo/main.svg` returns valid SVG, renders in GitHub README.

---

### Phase 7: Billing & Tier Enforcement (Week 9)

**Tasks:**
- [ ] Stripe integration (subscriptions + webhooks)
- [ ] Open Source tier: auto-detect via GitHub API (public repo + OSS license)
- [ ] Quota middleware: check analyses_used + fixes_used against tier limits
- [ ] Billing API routes + Stripe webhook handler
- [ ] Coolify deployment config + env var documentation

**Validate:** Free tier hits limit → 429 returned → upgrade flow works.

---

### Phase 8: Rego Rule Completion (Week 10)
Complete full initial ruleset (20+ rules).

**Tasks:**
- [ ] Write all Rego rules (all categories, at least 3 per category)
- [ ] Unit tests per rule (violating + compliant cases)
- [ ] Rule metadata in DB (severity weights for scoring)
- [ ] Rules API endpoint (list, detail, enable/disable per org)
- [ ] Rules page in frontend

**Validate:** 80%+ coverage on rules, no false positives on top 10 popular GH Actions workflows.

---

## Key Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| Rego evaluation | OPA REST sidecar | Language-agnostic, production-grade, testable |
| LLM abstraction | LiteLLM + LangChain | Unified interface across all providers |
| Task queue | Celery + Redis | Standard Python async tasks, Flower monitoring |
| Dedup | SHA256(workflow_file_content) | Simple, deterministic, content-addressable |
| GitHub auth | GitHub App JWT + installation tokens | Scoped permissions, no user PATs needed |
| Fix delivery | PyGithub REST API | Simpler than GraphQL for PR/comment creation |
| Badge cache | Redis + `Cache-Control: max-age=300` | Avoid DB hit on every README load |
| LangSmith | `LANGCHAIN_TRACING_V2=true` env var | Zero-code tracing for all LangChain calls |

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| GitHub App rate limits (5000 req/hr/install) | Medium | Cache fetched workflow files, only refetch on push events |
| OPA startup latency | Low | Run OPA as sidecar service, warm on start |
| LLM fix quality variance | High | Prompt templates per rule, human review step before auto-merge |
| Rego rules false positives | Medium | Conservative rules first, test against real-world workflows |
| Celery task fan-out on large orgs | Medium | Per-tier concurrency limits, priority queues |
| GitHub webhook delivery failures | Low | Idempotent task handlers, webhook replay support |

---

## Acceptance Criteria

- [ ] All 8 phases complete
- [ ] 80%+ test coverage (Pytest + Playwright)
- [ ] Static analysis end-to-end under 30s per repo
- [ ] LLM fix pipeline end-to-end under 2min
- [ ] Badge SVG renders correctly in GitHub README
- [ ] All 5 rule categories have at least 3 rules each
- [ ] Free tier quota enforcement verified
- [ ] `docker compose up` starts all services with no manual config beyond `.env`
- [ ] LangSmith traces visible for all LLM calls
- [ ] Deduplication verified: identical workflow submitted twice → single analysis record
