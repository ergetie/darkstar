## ADDED Requirements

### Requirement: Interrupted apply recovery
When the updater starts and the persisted apply is `building` or `restarting`, it SHALL decide the outcome from the version the Darkstar container reports, not from the interruption itself, and the apply SHALL stay in progress meanwhile. The apply record SHALL persist the previous commit, branch, version and channel before the first change to the checkout.

#### Scenario: Target is running
- **WHEN** the updater restarts mid-apply and the container reports the target version
- **THEN** the apply becomes `done` ("Updated to <target>"), so an open UI reloads onto the new version, and the updater self-recreate rule applies as after a normal `done`

#### Scenario: Old version still running
- **WHEN** the updater restarts during checkout or build and the container reports the previous version on two consecutive polls
- **THEN** the checkout is restored to the previous commit and branch, and the apply is `failed` with "Update was interrupted; nothing changed, safe to retry"

#### Scenario: Restore fails
- **WHEN** the old version is running but the checkout cannot be restored
- **THEN** the apply is `failed` with a message naming the manual `git checkout` command for the previous commit

#### Scenario: Container still starting
- **WHEN** the container is unreachable at start-up and reports the target within 5 minutes
- **THEN** the apply becomes `done`, the checkout is untouched

#### Scenario: Uncertain outcome
- **WHEN** the container stays unreachable, or reports neither the target nor the previous version, for 5 minutes
- **THEN** the apply is `failed` with "Update was interrupted and Darkstar did not report the expected version; the checkout was left untouched", pointing at `docker compose logs darkstar`, and nothing is restored

#### Scenario: Record without previous state
- **WHEN** the interrupted record has no previous state (killed before it was written)
- **THEN** a running target is `done`; anything else is `failed` with the checkout left untouched

#### Scenario: Decision in progress
- **WHEN** the updater is deciding the outcome of an interrupted apply
- **THEN** the apply is `restarting`, new applies and checks are refused, the running version is polled for at most 5 minutes (the apply health timeout), and neither the checkout nor the database is changed unless the outcome is certain

#### Scenario: Stale failure for the installed version
- **WHEN** a `failed` apply targets the version the running container reports (also after a check)
- **THEN** the apply is cleared to `idle`; an unreachable container or another running version leaves the record untouched, including when only the checkout is at the target

## MODIFIED Requirements

### Requirement: UI feedback and reconnect
The UI SHALL show update state, let the user switch channel, check, and confirm an update, show live progress, and reconnect automatically after the restart. While an update is in progress, or Darkstar is restarting as part of it, the UI SHALL NOT show any instruction to run a host command (neither "updater unavailable" nor "updater outdated" hints); it SHALL show progress or a neutral "updater not responding, the update continues" message instead. "In progress" SHALL be tracked at app level, survive closing and reopening the card, and SHALL NOT be reset by a response without apply data (`reachable: false`).

#### Scenario: Layout
- **WHEN** an update is available
- **THEN** a dot shows next to the version in the sidebar (and the mobile nav); clicking the version opens a floating card with current/target version, channel selector, Check now, Update (with confirm), messages, live log and restarting state; a dismissible banner announces the update and dismissal persists per target version

#### Scenario: Unhealthy
- **WHEN** the new container is not healthy within 5 minutes
- **THEN** the UI shows the failure with a pointer to the updater log

#### Scenario: Restart
- **WHEN** the container restarts after apply
- **THEN** the UI shows "Restarting" and reconnects automatically without manual reload

#### Scenario: Updater outdated mid-update
- **WHEN** the checkout already holds a newer updater (updater reports `updater_outdated`) while the apply is `building` or `restarting`
- **THEN** the "run docker compose up -d --build updater" hint is hidden

#### Scenario: Updater not responding mid-update
- **WHEN** the updater answers `reachable: false` after the user started an update and the card was closed and reopened
- **THEN** the card shows "Updater not responding, the update continues" and no command; the hint to run `docker compose up -d updater` only appears when no update is in progress

#### Scenario: Guard expires
- **WHEN** no in-progress apply state has been observed for 10 minutes while the updater stays unreachable
- **THEN** the in-progress guard ends and the "updater unavailable" hint may appear
