# Capability: Load Slot Blend

## Purpose

Blend the median load model with the same-slot 7-day average so planned energy matches actual consumption, keeping the uncertainty bands consistent.

## Requirements

### Requirement: Blended load middle forecast
When load models are available, the stored load middle forecast per slot SHALL be `LOAD_BLEND_MODEL_WEIGHT x model_p50 + LOAD_BLEND_SLOT_WEIGHT x slot_mean_7d` with weights 0.4 and 0.6 as code constants (not user config). `slot_mean_7d` is the mean actual load of the same 15-minute local slot over the previous 7 local days, using only observations strictly before the forecast is made, only days that survive the training data rule, and only days where that slot exists.

#### Scenario: Normal blend
- **WHEN** 7 clean prior days have that slot with mean 0.30 kWh and model p50 is 0.20
- **THEN** the stored middle forecast SHALL be 0.26 kWh

#### Scenario: No leakage
- **WHEN** a slot is in the future or is the current slot
- **THEN** no observation at or after the forecast time SHALL enter `slot_mean_7d`

### Requirement: Fallback to model alone
If fewer than 3 prior days provide the slot, the middle forecast SHALL be the model p50 alone for that slot.

#### Scenario: Sparse history
- **WHEN** only 2 prior days have the slot
- **THEN** the forecast SHALL equal model p50

### Requirement: Bands stay consistent
Load p10 and p90 SHALL be shifted by the same per-slot delta (`blended - model_p50`), clamped to the existing floor (0.01 kWh) and ceiling, and ordered p10 <= p50 <= p90 by the existing repair. The spread `p90 - p50` consumed by the probabilistic S-Index SHALL therefore remain the model's spread except where clamping applies.

#### Scenario: Ordering
- **WHEN** the delta is -0.5 kWh and p10 is 0.2
- **THEN** stored p10 SHALL be 0.01 and p10 <= p50 <= p90 SHALL hold

### Requirement: Disabled paths unchanged
The blend SHALL NOT apply when load models are unavailable (baseline path) or Aurora load forecasting is disabled.

#### Scenario: Baseline path
- **WHEN** no load models loaded
- **THEN** the existing 0.0 placeholder behavior SHALL be unchanged
