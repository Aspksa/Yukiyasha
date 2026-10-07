# Changelog

All notable changes to Yukiyasha are documented here.

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
