# Changelog

All notable changes to Yukiyasha are documented here.

## [0.2.1] - 2026-10-07

### Fixed
- atomic file replacement and race-safe `overwrite=false`;
- exact newline preservation on Windows and Linux;
- precise disk-domain errors and consistent HTTP status mapping;
- non-empty directory handling no longer masks unrelated OS errors;
- missing disk directories now return 404;
- module FAILED state, startup rollback and complete shutdown attempts;
- runtime start timestamp now reflects actual starts and restarts;
- disk endpoints no longer block the event loop;
- web tests no longer touch the real Yukiyasha disk;
- Windows launcher port fallback and paths containing `!`;
- launcher dependency synchronization after `pyproject.toml` changes.

### Security
- 2 MiB HTTP request-body cap before JSON parsing;
- Host validation against DNS rebinding;
- browser Origin validation for disk API requests;
- symlink escape protection is covered by tests.

### Changed
- default disk root is now `~/.yukiyasha/disk`;
- package version is read through `importlib.metadata`;
- Windows CI avoids installing the project twice.

## [0.2.0] - 2026-10-07

### Added
- explicit module manifests, registry and lifecycle;
- module health snapshots and `GET /api/modules`;
- first module: **Диск Yukiyasha**;
- sandboxed file listing, UTF-8 read/write and delete API;
- configurable disk root through `YUKIYASHA_DISK_DIR`;
- traversal, absolute-path and symlink-listing protections;
- 1 MiB text read/write safety limit;
- module and disk API tests.

## [0.1.0] - 2026-10-07

### Added
- modular Python core and runtime lifecycle;
- environment-driven configuration;
- FastAPI application and health/runtime API;
- responsive dark web dashboard;
- automated runtime and API tests;
- Ruff linting and cross-platform GitHub Actions CI;
- architecture and project-state documentation.
