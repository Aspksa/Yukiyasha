# Yukiyasha Architecture

## v0.6.0 — modular monolith with human-approved proposals

```text
Browser -> Web/API -> Core Runtime -> Module Registry -> Modules
                           |               |
                           +-> Permissions +-> scoped capabilities
                           +-> Audit
```

Core and modules do not import the Web/API layer.

## Runtime and capabilities

The runtime owns a default-deny `PermissionBroker`. Modules receive scoped facades instead of
raw dependencies.

Current scopes:
- `memory`: disk access under `memory/**`;
- `primavtodor`: disk access under `projects/work/Примавтодор/**`;
- `proposals`: disk access under `proposals/**` plus controlled Примавтодор mutation access;
- `ai`: disk access under `ai/**`, read-only Примавтодор access, Memory access, and
  `proposal.create`.

The AI module is not granted direct Примавтодор mutation capability and has no proposal
approve/reject capability.

## Proposal lifecycle

Proposal files live under `proposals/items/*.json`.

The mutation body is fixed at creation. Lifecycle status may transition only from `pending` to
one of `applied`, `rejected`, or `stale`.

The assistant can only create a proposal through `primavtodor_propose_change`.
For update/delete proposals, creation captures a fingerprint of the current record values and
timestamp. Approval re-reads that target; if it changed, the proposal becomes `stale` and no
business write occurs.

Partial updates are merged with current values and dry-run validated before the proposal is
stored. Create proposals are also validated before persistence.

Only the local human-facing API resolves proposals:
- `POST /api/proposals/{id}/approve`;
- `POST /api/proposals/{id}/reject`.

Completed proposals are one-shot and cannot be applied again.

## Audit

Audit events live under `system/audit/YYYY-MM-DD/*.json`. Proposal events record proposal id,
operation, kind and outcome without copying the proposed business payload.

## Memory

Long-term Memory remains separate from chat history under `memory/items/*.json`. Search is local
lexical retrieval, and Memory mutations still require explicit current-message intent.

## Assistant tool flow

For a tool-relevant message:
1. local routing chooses the tool definitions;
2. the provider may request standard function calls;
3. local capability and intent checks run again before execution;
4. results are audited and masked where appropriate;
5. the final response is streamed and saved after completion.

Business tools provide reads plus proposal creation. Memory tools provide search and explicitly
requested remember/forget operations. The assistant cannot directly apply a business mutation.

## Примавтодор

Structured records remain schema-driven and enforce uniqueness, references, seasonal rules and
delete constraints. `Records.validate()` now provides dry-run normalization for proposal
creation without mutating storage.

## Web/API boundary

FastAPI retains TrustedHost validation, same-origin protection for mutations, request-size limits,
security headers, no-store API responses and threadpool execution for synchronous filesystem work.

## Next architecture step

Add an in-context proposal review surface to the assistant/workspace: show the concrete diff,
status and stale reason, with approve/reject controls only inside the proposal context rather than
as global navigation actions.
