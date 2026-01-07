---
description: Version Release Supervisor
---

## Phase 1: Validation

1. **Git Hygiene**: Check if \`git status\` is clean. If not, **STOP**.
2. **Lint & Test**: Run \`./lint.sh\` (or \`cd frontend && pnpm lint\` + \`ruff check .\`).
3. **Failure Check**: If tests fail, **STOP**.

## Phase 2: Update Version Numbers

1. **Update HA Manifest**: Change the \`version:\` key in [darkstar/config.yaml](./config.yaml).
2. **Update Startup Banner**: Update the version string in [darkstar/run.sh](./run.sh) (Line ~157).
3. **Update Frontend**: Update the \`version:\` key in [frontend/package.json](./frontend/package.json).
4. **Update Monorepo Root**: Update the \`version:\` key in [package.json](./package.json).
5. **Verification**: Run \`grep -r "[new_version]" .\` to confirm all files updated.

## Phase 3: Git Operations

1. **Stage changes**: \`git add darkstar/config.yaml darkstar/run.sh frontend/package.json package.json\`
2. **Commit**: \`git commit -m "chore(release): bump to v[new_version]"\`
3. **Tag**: \`git tag v[new_version]\`
4. **Push**: \`git push origin main --tags\`

## Phase 4: CI/CD Trigger

1. **Notify user**: "Tags pushed. GitHub Actions (\`build-addon.yml\`) should now be building the Multi-arch Docker images."