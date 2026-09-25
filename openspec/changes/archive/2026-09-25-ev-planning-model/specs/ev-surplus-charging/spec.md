## REMOVED Requirements

### Requirement: Surplus EV energy counts toward the daily quota
**Reason**: Per-day EV quotas no longer exist (`ev-planning-model`).
**Migration**: Planned surplus energy counts toward `delivered_in_horizon` in the goal requirement and appears in `planned_by_day` (`ev-deferral-value`).
