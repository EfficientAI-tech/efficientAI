# Workspace RBAC: Capability-Based Access Control

## Approved Design Decisions

- **Default-closed**: org members only access workspaces they're explicitly granted; org admins implicitly access all workspaces.
- **Capability-based roles**: predefined system roles (Viewer, Editor, Workspace Admin) plus org-admin-definable custom roles composed from a fixed capability registry.
- **Membership management**: org admins + holders of `workspace.members.manage` in that workspace.
- **API keys stay org-wide** (bypass workspace RBAC); key scoping deferred.
- **Enforcement**: capability registry + role tables + per-route `require_capability()` dependencies.

## Data Model

### Capability registry (`app/core/auth/capabilities.py`)

| Domain | Capabilities |
|---|---|
| Calls | `calls.view`, `calls.import`, `calls.delete` |
| Metrics | `metrics.view`, `metrics.manage` |
| Evaluations | `evals.view`, `evals.run` |
| Simulation | `sim.view`, `sim.manage` |
| Reports | `reports.view`, `reports.generate` |
| Workspace | `workspace.settings`, `workspace.members.view`, `workspace.members.manage` |

### Tables

- `workspace_roles`: `id`, `organization_id`, `name`, `description`, `capabilities` (JSON), `is_system`, timestamps; unique `(organization_id, name)`
- `workspace_members`: `id`, `workspace_id`, `user_id`, `role_id`, `added_by_user_id`, timestamps; unique `(workspace_id, user_id)`

### System roles (seeded per org)

- **Viewer** — all `*.view` capabilities
- **Editor** — Viewer + `calls.import`, `evals.run`, `metrics.manage`, `sim.manage`, `reports.generate`
- **Workspace Admin** — all capabilities

### Backfill

Every existing org member added to every org workspace: admin→Workspace Admin, writer→Editor, reader→Viewer.

## Backend Enforcement

- `WorkspaceContext` dependency resolves workspace + capability set
- Org admin → all capabilities; unbound API key → all; else membership lookup
- `require_capability(cap)` on workspace-scoped routes
- Org `ReaderReadOnlyMiddleware` unchanged

## API

- Workspace lifecycle: filtered list, create with auto-admin membership, settings/delete guards
- `workspace_iam.py`: members CRUD, workspace-roles CRUD, capabilities registry

## Frontend

- Filtered workspace switcher, members page, roles builder in IAM settings
- `useWorkspaceCapabilities()` hook for cosmetic UI gating

## Rollout

Backfill preserves existing access on upgrade; admins prune memberships via new UI.
