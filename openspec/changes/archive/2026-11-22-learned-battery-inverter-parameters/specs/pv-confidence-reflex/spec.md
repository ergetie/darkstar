## REMOVED Requirements

### Requirement: Relative bias decides confidence changes
**Reason**: Reflex is removed. `pv_confidence_percent` could not converge (its own changes never reach the stored forecast it measured) and is now a plain manual setting.
**Migration**: Set `forecasting.pv_confidence_percent` in Settings. Its current value in `config.yaml` is kept as the user's manual setting.
