# Yukiyasha Project State

## Current release

- Version: **0.1.0**
- Stage: **Foundation / Core + Web**
- Branch under development: `feat/v0.1.0-foundation-web`

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
- GitHub Actions CI on Ubuntu and Windows for Python 3.11-3.13.
- Architecture and changelog documentation.

## Invariants

- Core does not depend on the web layer.
- Browser state is derived from API state.
- The version for this release is 0.1.0.
- CI must be green before merge to main.

## Known limitations

- No persistence.
- No authentication.
- No LLM/provider integration.
- No memory or module runtime.
- No deployment configuration yet.

## Exact next_action

After v0.1.0 is green and merged, build **v0.2.0 Module Runtime Foundation**:
module manifest -> discovery -> validation -> registry -> lifecycle -> health ->
permissions boundary, while keeping modules isolated from the web transport.
