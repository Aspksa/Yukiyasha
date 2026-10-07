# Yukiyasha Project State

## Current release

- Version: **0.2.1**
- Stage: **Module Runtime / Hardening**
- Status: **release candidate**
- First module: **Диск Yukiyasha**

## Implemented

- Module manifest and registry.
- Lifecycle states including FAILED.
- Startup rollback and best-effort shutdown of all modules.
- Runtime degraded mode when module startup fails.
- Runtime start timestamp set on every actual start.
- Atomic disk writes and atomic no-overwrite publication.
- Exact UTF-8/newline preservation.
- Consistent disk API error mapping: 400/403/404/409/413/500.
- 1 MiB text limit and 2 MiB HTTP body limit.
- Stable default disk root under `~/.yukiyasha/disk`.
- Host and browser Origin validation for the local API.
- Module Примавтодор (skeleton): owns the `projects/work/Примавтодор` folder; domain features come later.
- Browser workspace: file browser, text editor, create/delete and system page backed by Yukiyasha Disk.
- Isolated API tests using temporary disk roots.
- Windows launcher dependency fingerprinting and safer port fallback.
- Two-tier GitHub Actions CI with stable `PR Gate`.

## CI strategy

- Pull requests: Fast quality + Windows launcher + PR Gate.
- Main/nightly: full Ubuntu + Windows matrix for Python 3.11-3.13.
- Stale runs are cancelled with concurrency groups.
- Windows launcher diagnostics install runtime dependencies only once.

## Invariants

- Core does not depend on the web layer.
- Modules do not depend on the web layer.
- Disk paths cannot escape the configured sandbox root.
- Disk writes do not expose partially written replacement files.
- Tests must not write to the user's real disk root.
- The package version is sourced from installed package metadata.
- CI must be green before merging feature work to main.

## Known limitations

- Permission declarations are metadata only; central authorization is not implemented yet.
- Disk API currently supports UTF-8 text files only.
- No authentication.
- Local security assumes binding to loopback; remote serving is not supported yet.
- No LLM/provider integration.
- No memory module.
- No deployment configuration yet.

## Exact next_action

Implement the **permissions boundary** so declared module permissions become enforced runtime
capabilities before storing valuable user data or adding additional modules.
