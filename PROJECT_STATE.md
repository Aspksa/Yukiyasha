# Yukiyasha Project State

## Current release

- Version: **0.5.0**
- Stage: **Permissioned assistant memory**
- Status: **released** (see `CHANGELOG.md`)
- Modules: **Диск Yukiyasha**, **Память**, **Примавтодор**, **Помощник**

## Implemented

- Module manifest and registry with lifecycle states including FAILED.
- Startup rollback and best-effort shutdown of all modules.
- Runtime degraded mode when module startup fails.
- Runtime-owned **PermissionBroker** with default-deny checks.
- Path-scoped **DiskAccess** capabilities:
  - Память can access only `memory/**`;
  - Примавтодор can access only `projects/work/Примавтодор/**`;
  - AI can access only `ai/**`.
- Explicit assistant capabilities for `primavtodor.read` and `memory.read/write/delete`.
- Persistent audit events under `system/audit/YYYY-MM-DD/*.json`.
- AI tool masking before Примавтодор disclosure.
- Read-only AI tools for Примавтодор records, timesheet and settings.
- Long-term Memory module:
  - one JSON file per memory under `memory/items/**`;
  - local token-overlap search;
  - deduplication, item/size limits and lifecycle health;
  - explicit remember/forget gating for AI;
  - credential-like material rejected before persistence;
  - audit metadata excludes memory text and search query.
- Direct memory API for listing, searching, adding and removing entries.
- Standard OpenAI-compatible tool planning with ordinary-chat fallback when provider tools are unsupported.
- No AI create/update/delete tools for Примавтодор.
- Atomic disk writes, sandbox validation and request limits.
- Stable default disk root under `~/.yukiyasha/disk`.
- Host, same-origin and browser security protections.
- Примавтодор linked records, seasonal fuel norms, timesheet, REST API and UI.
- Browser workspace and Windows launcher with two-tier GitHub Actions CI.

## CI strategy

- Pull requests: Ruff + Python tests + JS helper tests + wheel packaging + Windows launcher + PR Gate.
- Main/nightly: Ubuntu + Windows × Python 3.11-3.13.
- CI must be green before merging feature work.

## Security invariants

- Module-to-module capability access is default-deny.
- Module disk access is both permission-checked and path-scoped.
- AI business access remains read-only.
- AI memory mutations require explicit remember/forget wording from the current user message.
- Memory and business tool actions are audited without copying disclosed content into audit records.
- Credential-like material is not accepted into long-term memory.
- Core/modules do not depend on the web layer.
- Disk paths cannot escape the configured sandbox root.

## Known limitations

- No authentication; Yukiyasha remains a loopback-only local application.
- `ai.provider` is declared but provider-network access is not wrapped as its own capability.
- Audit retention/rotation and an audit viewer UI are not implemented.
- Memory retrieval is lexical, not semantic/vector-based.
- Memory has no dedicated browser management page yet; management is through API or explicit chat commands.
- Tool support depends on the provider implementing standard OpenAI-compatible `tools`.
- No write proposal/approval workflow for Примавтодор yet.
- No deployment configuration yet.

## Exact next_action

Implement a **write proposal / human approval boundary** for Примавтодор: the assistant may draft a
mutation, but it must not execute until the user explicitly approves that concrete proposal.
