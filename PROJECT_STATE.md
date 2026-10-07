# Yukiyasha Project State

## Current release

- Version: **0.4.0**
- Stage: **Permissions / audited read-only AI tools**
- Status: **released** (see `CHANGELOG.md`)
- Modules: **Диск Yukiyasha**, **Примавтодор**, **Помощник**

## Implemented

- Module manifest and registry with lifecycle states including FAILED.
- Startup rollback and best-effort shutdown of all modules.
- Runtime degraded mode when module startup fails.
- Runtime-owned **PermissionBroker** with default-deny checks.
- Path-scoped **DiskAccess** capabilities:
  - Примавтодор can access only `projects/work/Примавтодор/**`;
  - AI can access only `ai/**`.
- Explicit `primavtodor.read` capability for assistant tools.
- Persistent audit events under `system/audit/YYYY-MM-DD/*.json`.
- AI tool masking before provider disclosure: phone, personnel number and fuel-card values are masked.
- AI read-only tools:
  - list/get Примавтодор records;
  - read timesheet;
  - read current settings/season.
- Standard OpenAI-compatible tool planning with ordinary-chat fallback when provider tools are unsupported.
- No AI create/update/delete tools for Примавтодор.
- Atomic disk writes, exact UTF-8/newline preservation and sandbox path validation.
- 1 MiB text limit and 2 MiB HTTP request-body limit.
- Stable default disk root under `~/.yukiyasha/disk`.
- Host, same-origin and browser security-header protections.
- Примавтодор linked records, seasonal fuel norms, timesheet, REST API and UI.
- Browser workspace with file manager/editor, Примавтодор pages and assistant.
- Windows launcher checks and two-tier GitHub Actions CI.

## CI strategy

- Pull requests: Ruff + Python tests + JS helper tests + wheel packaging + Windows launcher + PR Gate.
- Main/nightly: Ubuntu + Windows × Python 3.11-3.13.
- CI must be green before merge.

## Security invariants

- Module-to-module capability access is default-deny.
- Module disk access is both permission-checked and path-scoped.
- AI receives only read-only Примавтодор capabilities.
- Sensitive tool fields are masked before provider transmission.
- A tool result is disclosed only after its audit event has been written successfully.
- Audit records contain action metadata, not the returned business payload.
- Core/modules do not depend on the web layer.
- Disk paths cannot escape the configured sandbox root.

## Known limitations

- No authentication; Yukiyasha is still a loopback-only local application.
- `ai.provider` is declared but provider-network access is not yet wrapped as its own capability.
- Audit retention/rotation and an audit viewer UI are not implemented yet.
- The assistant has no separate long-term Memory module.
- The assistant can read only structured Примавтодор records/settings/timesheet, not document folders.
- Tool support depends on the provider implementing the standard OpenAI-compatible `tools` format.
- No write proposals/approval workflow yet.
- No deployment configuration yet.

## Exact next_action

Add a **Memory module** behind the same permission/audit boundary, then add **write proposals**
that never mutate Примавтодор until a person explicitly approves the proposed change.
