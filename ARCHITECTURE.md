# Yukiyasha Architecture

## v0.2.0 module foundation

Yukiyasha remains a modular monolith, but modules now have an explicit runtime boundary.

### Layers

1. **Core**
   - process/runtime lifecycle;
   - owns the module registry;
   - no dependency on FastAPI or browser code.

2. **Application configuration**
   - immutable environment-driven settings;
   - service identity, version and module paths.

3. **Modules**
   - explicit manifest;
   - registration and lifecycle;
   - health snapshots;
   - permissions declared by each module;
   - modules do not import the web layer.

4. **Web/API**
   - transport only;
   - exposes core/module state and module operations.

### Dependency rule

```text
Browser -> Web/API -> Core -> Module Registry -> Modules
                    -> Configuration
```

Core and modules never import from Web/API.

## First module: Диск Yukiyasha

The Disk module is local sandboxed storage.

Default root:

```text
data/disk
```

Override with:

```text
YUKIYASHA_DISK_DIR
```

Security invariants:
- absolute paths are rejected;
- `..` traversal outside the disk root is rejected;
- symlink entries are not exposed by directory listings;
- text API reads/writes are capped at 1 MiB;
- deleting the disk root is forbidden.

Declared permissions:
- `disk.read`
- `disk.write`
- `disk.delete`

### API

- `GET /api/modules` — module manifests, lifecycle state and health;
- `GET /api/disk?path=` — list a directory;
- `GET /api/disk/file?path=` — read UTF-8 text;
- `PUT /api/disk/file` — write UTF-8 text;
- `DELETE /api/disk/file?path=` — delete a file or empty directory.

### Engineering rules

- every release changes the canonical project version;
- behavior changes require tests;
- main should only receive green CI;
- project state must record the exact next action;
- modules are added behind explicit interfaces, not by coupling into the UI.
