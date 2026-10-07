# Yukiyasha Architecture

## v0.8.0 — modular monolith with rich in-chat document objects

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

### Printing, import and reports

`printing.py`, `fuelcard.py` and `fuelreport.py` fill the organisation's own blank workbooks
(`forms/*.xlsx`, bundled with the package, no personal data in them) with `openpyxl`; they are
pure (plain values in, `.xlsx` bytes out). The waybill sheet holds the form twice side by side, so
every value is written in both halves. The monthly card and the report keep live `SUM` formulas.
`statement.py` reads the fuel-card provider's `.xls`/`.xlsx` (Windows-1251 for `.xls`);
`fuel_import.py` matches each fill-up card -> employee -> the driver's waybill on that date,
reports what it cannot match and skips what is already on file. Print settings (organisation,
signers, control wording) live next to the season in `settings.json`.

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

## Proposal review UI

The assistant view renders proposal cards directly inside the chat panel. Cards show operation,
target, status, reason and a field-level diff built from the immutable `before` snapshot and
normalized proposal payload. Pending cards expose approve/reject controls only in that local
context. Applied/rejected/stale cards remain visible as recent history without action controls.

The review UI is presentation-only: it calls the existing human-facing proposal API and does not
grant the AI any new capability.

## Document cards

Document discovery is metadata-only for the provider. The assistant can list files in the five
Примавтодор document sections, and the resulting document refs are persisted on the assistant
message. The browser renders those refs as mini-document cards with title, section, format and
size. Text preview is then fetched locally through the existing same-origin Disk API, so preview
content is not disclosed to the AI provider merely for presentation.

The stored path is an internal navigation locator only; it is not shown as a raw link. Opening a
card routes into the existing Yukiyasha file editor.

## Next architecture step

Extend the proposal model to timesheet marks and selected document create/update operations, while
reusing these document cards as the review surface.
