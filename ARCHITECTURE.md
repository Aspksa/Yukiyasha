# Yukiyasha Architecture

## v0.2.1 hardened module foundation

Yukiyasha is a modular monolith with explicit runtime, module and transport boundaries.

### Layers

1. **Core**
   - owns runtime lifecycle and the module registry;
   - coordinates degraded/ready/stopped state;
   - does not depend on FastAPI or browser code.

2. **Application configuration**
   - immutable environment-driven settings;
   - service identity and stable storage paths;
   - package version comes from installed package metadata.

3. **Modules**
   - explicit manifest;
   - registered/ready/failed/stopped lifecycle;
   - health snapshots;
   - declared permissions;
   - no dependency on the web layer.

4. **Web/API**
   - transport and HTTP safety boundary;
   - request body, Host and same-origin validation;
   - security headers (CSP without inline code, no framing, no MIME sniffing) and cache rules;
   - synchronous filesystem endpoints run through FastAPI's threadpool.

### Dependency rule

```text
Browser -> Web/API -> Core -> Module Registry -> Modules
                    -> Configuration
```

Core and modules never import from Web/API.

## Диск Yukiyasha

Default root:

```text
~/.yukiyasha/disk
```

Override with `YUKIYASHA_DISK_DIR`.

Security and consistency invariants:
- absolute paths and traversal outside the disk root are rejected;
- symlink escapes are rejected;
- replacement writes use a temporary file in the destination directory and `os.replace`;
- no-overwrite publication uses an atomic hard-link operation;
- UTF-8 bytes are read/written directly so line endings are never translated by the OS;
- text API reads/writes are capped at 1 MiB;
- HTTP request bodies are capped at 2 MiB before application parsing;
- internal temporary files are recognised by exact name shape, never by prefix alone;
- built-in project directories are protected by file identity, not by path spelling;
- the fully resolved path (not only symlink flags) must stay inside the root;
- deleting the disk root is forbidden;
- permission, conflict, invalid-path and size failures are represented explicitly.

Declared permissions remain metadata in v0.2.1:
- `disk.read`
- `disk.write`
- `disk.delete`

The next architecture step is enforcing those declarations through a central permission boundary.
