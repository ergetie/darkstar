## REMOVED Requirements

### Requirement: EV loss parameters are learned automatically
**Reason**: Reflex is removed. This job never ran automatically and never changed a value on production; the three-parameter loss model is not identifiable from constant-power sessions.
**Migration**: `charge_efficiency`, `charge_overhead_kw` and `start_loss_kwh` stay per-charger manual settings. Learning charge efficiency from car-meter sessions is a follow-up change.
