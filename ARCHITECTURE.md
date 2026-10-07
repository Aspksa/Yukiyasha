# Yukiyasha Architecture

## v0.1.0 foundation

Yukiyasha starts as a modular monolith. This keeps the first release simple while
preserving clear boundaries for future modules.

### Layers

1. **Core**
   - process/runtime lifecycle;
   - domain state;
   - no dependency on FastAPI or browser code.

2. **Application configuration**
   - environment-driven immutable settings;
   - one place for service identity and version.

3. **Web/API**
   - FastAPI transport;
   - REST endpoints expose core state;
   - browser UI consumes the same API;
   - web code must not own core business state.

4. **Future modules**
   - memory;
   - agent runtime;
   - providers;
   - tools and permissions;
   - automation;
   - observability.

### Dependency rule

```text
Browser -> Web/API -> Core
                    -> Configuration
```

Core never imports from Web/API.

### Initial API

- `GET /` — browser application;
- `GET /api/health` — health probe;
- `GET /api/runtime` — runtime snapshot;
- `GET /docs` — generated OpenAPI UI.

### Engineering rules

- every release changes the canonical project version;
- behavior changes require tests;
- main should only receive green CI;
- project state must record the exact next action;
- modules are added behind explicit interfaces, not by coupling into the UI.
