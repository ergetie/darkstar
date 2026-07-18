# Delta: ci-quality-gate

## ADDED Requirements

### Requirement: Frontend lint runs the full react-hooks recommended rule set

The frontend ESLint configuration (`frontend/eslint.config.js`) SHALL enable the complete `eslint-plugin-react-hooks` recommended rule set without disabling any of its rules. In particular, `react-hooks/set-state-in-effect`, `react-hooks/static-components`, `react-hooks/purity`, and `react-hooks/immutability` SHALL be active at their recommended severity, and the frontend codebase SHALL lint clean under them.

#### Scenario: Lint gate catches hook-safety regressions

- **WHEN** `npx eslint .` (or the lint step of `scripts/ci_local.sh`) runs over the frontend
- **THEN** the four rules above are active and report zero findings on the codebase

#### Scenario: Rules are not silently disabled again

- **WHEN** the frontend ESLint config is inspected
- **THEN** it contains no `'off'` override for any `react-hooks/*` rule from the recommended set
