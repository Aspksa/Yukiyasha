# Yukiyasha Project State

## Current release

- Version: **0.2.0**
- Stage: **Module Runtime / First Module**
- Status: **release candidate**
- First module: **Диск Yukiyasha**

## Implemented

- Python application runtime.
- Module manifest model.
- Module registry with duplicate protection.
- Module lifecycle: registered -> ready -> stopped.
- Module health snapshots.
- First module: sandboxed local Yukiyasha Disk.
- Disk read/write/list/delete operations.
- Path traversal and absolute-path protection.
- 1 MiB text file safety limit.
- FastAPI module and disk endpoints.
- Configurable disk root through `YUKIYASHA_DISK_DIR`.
- Unit/API tests.
- Two-tier GitHub Actions CI with stable `PR Gate`.

## CI strategy

- Pull requests: Fast quality + Windows launcher + PR Gate.
- Main/nightly: full Ubuntu + Windows matrix for Python 3.11-3.13.
- Stale runs are cancelled with concurrency groups.
- Feature-branch push checks are intentionally removed to avoid duplicate PR runs.

## Invariants

- Core does not depend on the web layer.
- Modules do not depend on the web layer.
- Disk paths cannot escape the configured sandbox root.
- Browser/API state is derived from runtime/module state.
- The canonical release version is 0.2.0.
- CI must be green before merging feature work to main.

## Known limitations

- Permission declarations exist, but central runtime authorization is not implemented yet.
- Disk API currently supports UTF-8 text files only.
- No authentication.
- No LLM/provider integration.
- No memory module.
- No deployment configuration yet.

## Exact next_action

Build the **permissions boundary** around module operations, then add a browser UI for
Диск Yukiyasha and use the disk as the persistence base for the future Memory module.
