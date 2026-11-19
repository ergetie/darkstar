# Spec: Frontend Typecheck Build Gate

## Purpose
Catch type and build errors in CI and before push.

## Requirements

### Requirement: CI runs typecheck and build
The frontend CI job SHALL run `pnpm typecheck` and `pnpm build`.

#### Scenario: Type error
- **WHEN** a TypeScript error is introduced
- **THEN** the frontend CI job fails

### Requirement: Local gate matches CI
`scripts/ci_local.sh` SHALL run frontend typecheck, vitest and build.

#### Scenario: Pre-push
- **WHEN** the pre-push gate runs with pnpm available
- **THEN** typecheck, tests and build all execute
