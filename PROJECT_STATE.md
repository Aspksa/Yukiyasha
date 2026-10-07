# Yukiyasha Project State

## Current release

- Version: **0.1.0**
- Stage: **Foundation / Core + Web**
- Status: **merged to main**
- Release baseline commit: `ef68af0`

## Implemented

- Python package foundation.
- Immutable environment configuration.
- Runtime lifecycle: starting -> ready -> stopped.
- Runtime snapshot DTO.
- FastAPI application.
- Health endpoint.
- Runtime telemetry endpoint.
- Responsive browser dashboard.
- Unit/API tests.
- Ruff quality gate.
- Two-tier GitHub Actions CI: fast PR checks plus full compatibility matrix.
- Architecture and changelog documentation.

## CI strategy

- Pull requests: Ubuntu/Python 3.12 + separate Windows launcher check.
- Main/nightly: full Ubuntu + Windows matrix for Python 3.11-3.13.
- Stale runs are cancelled with concurrency groups.
- Documentation-only changes skip Python CI.
- Feature-branch push checks are intentionally removed to avoid duplicate PR runs.

## Verification

- v0.1.0 feature branch CI: **green**.
- Ruff: **passed**.
- Pytest: **passed**.
- Platforms: **Ubuntu + Windows**.
- Python: **3.11, 3.12, 3.13**.

## Invariants

- Core does not depend on the web layer.
- Browser state is derived from API state.
- The version for this release is 0.1.0.
- CI must be green before merging feature work to main.

## Known limitations

- No persistence.
- No authentication.
- No LLM/provider integration.
- No memory or module runtime.
- No deployment configuration yet.

## Exact next_action

Build **v0.2.0 Module Runtime Foundation**:
module manifest -> discovery -> validation -> registry -> lifecycle -> health ->
permissions boundary, while keeping modules isolated from the web transport.
