# Yukiyasha Architecture

## v0.4.0 — permissioned modular monolith

Yukiyasha remains a modular monolith:

```text
Browser -> Web/API -> Core Runtime -> Module Registry -> Modules
                           |               |
                           +-> Permissions +-> scoped capabilities
                           +-> Audit
```

Core and modules do not import the Web/API layer.

## Runtime and permission boundary

The runtime owns a `PermissionBroker`. Each module manifest declares permissions, and the broker
copies those grants at registration time. Unknown subjects and undeclared capabilities are denied
by default.

Raw service objects stay inside the runtime composition root. Dependencies receive capability
views instead:

- `DiskAccess` checks both a permission (`disk.read/write/delete`) and an allowed path root;
- Примавтодор receives a disk view limited to `projects/work/Примавтодор/**`;
- the AI module receives a disk view limited to `ai/**`;
- `PrimavtodorReadAccess` exposes only list/get records, timesheet and settings and requires
  `primavtodor.read`.

The Web/API layer is trusted application code and still calls runtime modules directly. The
boundary is specifically for module-to-module access and future AI capabilities.

## Audit

`AuditLog` is runtime-owned and writes one immutable JSON event per disclosure under:

```text
system/audit/YYYY-MM-DD/<timestamp>-<id>.json
```

AI tool execution is fail-closed: a result is returned to the provider only after the allowed
audit event is persisted. Audit metadata records the subject, tool name, outcome and identifiers;
it does not contain the returned business payload or API key.

## Модуль «Помощник»

The assistant keeps persona and conversations on its scoped `ai/**` disk capability.

For ordinary chat:
1. build persona + bounded history + new user message;
2. stream the final response from the configured OpenAI-compatible provider;
3. save the completed turn only after the whole answer arrives.

For a Примавтодор-related question:
1. local keyword routing decides whether tools are relevant;
2. a standard non-streaming OpenAI-compatible `tools` planning request is made;
3. at most four requested local tools are executed;
4. sensitive fields are masked;
5. each disclosure is audited;
6. tool result messages are sent back to the provider;
7. the final answer is streamed normally.

Providers that reject the standard `tools` fields with HTTP 400/422 fall back to ordinary chat.

Available tools are intentionally read-only:
- `primavtodor_list_records`;
- `primavtodor_get_record`;
- `primavtodor_timesheet`;
- `primavtodor_settings`.

Sensitive keys currently masked before provider transmission:
- phone;
- personnel number;
- fuel-card/card number fields.

There is no create/update/delete Примавтодор tool.

## Модуль Примавтодор

Примавтодор owns `projects/work/Примавтодор` and ten sections. Structured entities remain:
employees, vehicles, waybills and fuel; timesheet is computed from waybills plus manual marks.

Its records preserve the existing invariants:
- schema-driven validation;
- validated references and uniqueness;
- referenced records cannot be deleted;
- computed values are derived on read;
- closed waybills keep their historical season;
- all storage goes through its scoped disk capability in the runtime.

## Диск Yukiyasha

Default root is `~/.yukiyasha/disk` unless `YUKIYASHA_DISK_DIR` is set.

Storage invariants:
- absolute paths, traversal and symlink escapes are rejected;
- atomic replacement writes;
- race-safe no-overwrite publication with fallback;
- exact UTF-8 bytes/newlines;
- internal temp files are hidden/cleaned safely;
- built-in project directories are protected;
- text API limit is 1 MiB.

## Web/API boundary

FastAPI provides:
- TrustedHost validation;
- same-origin protection for disk reads and API mutations;
- 2 MiB request-body limit before application parsing;
- CSP, no-framing, no-MIME-sniffing and cache protections;
- synchronous filesystem endpoints executed in FastAPI's threadpool.

## Next architecture step

Add a permissioned **Memory module**, then introduce a proposal/approval layer for AI-assisted
writes. The assistant may propose a mutation, but only explicit human approval may execute it.
