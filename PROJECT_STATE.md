# Yukiyasha Project State

## Current release

- Version: **0.8.0**
- Stage: **Rich document objects in assistant chat**
- Status: **released** (see `CHANGELOG.md`)
- Modules: **Диск Yukiyasha**, **Память**, **Примавтодор**, **Предложения**, **Помощник**

## Implemented

- Runtime-owned default-deny `PermissionBroker`.
- Path-scoped `DiskAccess` for Memory, Примавтодор, Proposals and AI.
- Read-only AI access to Примавтодор and guarded long-term Memory.
- Proposal / approval boundary for structured Примавтодор mutations:
  - AI can only call `proposal.create`;
  - create/update/delete proposals are validated before persistence;
  - update proposals may be partial and are normalized to a full target state;
  - update/delete proposals capture a fingerprint of the source record;
  - approval re-checks the fingerprint and marks changed targets `stale`;
  - proposal bodies are never rewritten by AI and each proposal is one-shot;
  - human API endpoints can approve or reject pending proposals;
  - there is no AI apply/approve/reject capability.
- Proposal lifecycle statuses: `pending`, `applied`, `rejected`, `stale`.
- Assistant chat renders proposal cards with old/new diff and in-context approve/reject controls.
- Audit events for proposal creation and human resolution without proposal payload contents.
- Long-term Memory with explicit remember/forget gating and credential-like content rejection.
- Read-only AI tools for Примавтодор records, timesheet, settings and document metadata.
- Assistant replies persist structured document refs and render them as rich mini-document cards.
- Document previews are loaded locally in the browser; document contents are not sent to the AI provider just to render cards.
- Persistent audit log under `system/audit/YYYY-MM-DD/*.json`.
- Atomic disk writes, sandbox validation, request limits, security headers and same-origin checks.
- Примавтодор linked records, seasonal fuel norms, timesheet, REST API and UI.
- Windows launcher and two-tier GitHub Actions CI.
- Closing of the month and fuel control (unreleased): rules in `checks.py`, one screen, one zip, accepted findings, read-only assistant tool.
- Printing and fuel reports: waybill form № 3 as the organisation's own .xlsx, fuel-card statement import, monthly fuel card, monthly «Анализ расхода ГСМ». Forms № 3 спец. and № 4-П are not printable yet.

## CI strategy

- Pull requests: Ruff + Python tests + JS helper tests + wheel packaging + Windows launcher + PR Gate.
- Main/nightly: Ubuntu + Windows × Python 3.11-3.13.
- Merge only after required PR checks are green.

## Security invariants

- Module-to-module capability access is default-deny.
- AI cannot mutate Примавтодор directly.
- AI can only create a validated proposal; only the human-facing API can approve/reject it.
- Update/delete approval checks that the target did not change since proposal creation.
- A completed proposal cannot be applied again.
- Same-origin checks protect proposal approval/rejection endpoints.
- Proposal audit metadata excludes the proposed business payload.
- Memory and business tool audit records do not copy disclosed content.
- Core/modules do not depend on the web layer.

## Known limitations

- No authentication; Yukiyasha remains a loopback-only local application.
- Proposals cover structured records only; document files and timesheet marks are not proposal-enabled.
- `ai.provider` is declared but provider-network access is not wrapped as its own capability.
- Audit retention/rotation and an audit viewer UI are not implemented.
- Memory retrieval is lexical, not semantic/vector-based.
- Tool support depends on standard OpenAI-compatible `tools`.
- No deployment configuration yet.

## Exact next_action

Extend proposal coverage to **timesheet marks and selected document operations**, reusing the same
review-card and stale/approval model instead of introducing direct AI writes.
