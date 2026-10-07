# Yukiyasha Architecture

## v0.5.0 — permissioned modular monolith with long-term memory

```text
Browser -> Web/API -> Core Runtime -> Module Registry -> Modules
                           |               |
                           +-> Permissions +-> scoped capabilities
                           +-> Audit
```

Core and modules do not import the Web/API layer.

## Runtime and capability boundary

The runtime owns a default-deny `PermissionBroker`. Module manifests declare capabilities and
runtime composition supplies scoped facades rather than raw dependencies.

Current scopes:
- `memory` receives `disk.read/write/delete` only under `memory/**`;
- `primavtodor` receives `disk.read/write/delete` only under
  `projects/work/Примавтодор/**`;
- `ai` receives `disk.read/write/delete` only under `ai/**`;
- `ai` additionally receives `primavtodor.read` and `memory.read/write/delete`.

`PrimavtodorReadAccess` exposes only read operations. `MemoryAccess` exposes search, remember
and forget, each guarded by its own permission.

## Audit

`AuditLog` writes one JSON event per guarded AI tool action under:

```text
system/audit/YYYY-MM-DD/<timestamp>-<id>.json
```

Business payloads, memory text and memory search queries are not copied into audit records.
For business reads, disclosure is fail-closed: the result is returned only after its audit event
has been persisted.

## Memory module

Long-term memory is separate from chat history:

```text
memory/
  items/
    mem-<id>.json
```

Each item contains a stable id, text and timestamps. The module:
- normalizes whitespace and deduplicates exact text;
- caps each item at 2,000 characters and the store at 500 items;
- uses local token-overlap ranking for retrieval;
- rejects credential-like material before persistence;
- exposes direct list/search/add/delete HTTP endpoints for transparent management.

The assistant does not silently mine all conversations. Tool routing is lexical and only considers
memory tools for messages that look like recall/preference or explicit remember/forget requests.
`memory_remember` and `memory_forget` are not even advertised to the provider unless the current
message contains explicit matching intent, and execution re-checks that intent locally.

## Assistant tool flow

For an ordinary chat, the assistant streams the final provider response directly.

For a message that may need a tool:
1. local routing chooses the relevant tool family;
2. a standard OpenAI-compatible non-streaming tool-planning request is made;
3. at most four calls are accepted from the provider;
4. local permission and intent checks run;
5. results are masked/audited as appropriate;
6. tool result messages are returned to the provider;
7. the final answer is streamed and saved only after completion.

Current tools:
- `primavtodor_list_records`;
- `primavtodor_get_record`;
- `primavtodor_timesheet`;
- `primavtodor_settings`;
- `memory_search`;
- `memory_remember` — explicit user request required;
- `memory_forget` — explicit user request required.

There is still no Примавтодор write tool.

## Примавтодор

Примавтодор owns `projects/work/Примавтодор`. Existing schema, reference integrity, seasonal
fuel norms, timesheet derivation and immutable historical calculations remain unchanged. The AI
sees it only through the read-only facade.

## Disk and Web/API boundaries

Disk invariants remain:
- no absolute/traversal/symlink escape;
- atomic writes and race-safe no-overwrite;
- exact UTF-8 bytes/newlines;
- built-in directories protected;
- 1 MiB text limit.

FastAPI retains TrustedHost, same-origin mutation protection, 2 MiB body limit, security headers,
no-store API responses and threadpool execution for synchronous filesystem work.

## Next architecture step

Add a **proposal/approval boundary** for AI-assisted Примавтодор writes. A proposed mutation must
be stored as a concrete immutable proposal and cannot execute until the user explicitly approves
that exact proposal.
