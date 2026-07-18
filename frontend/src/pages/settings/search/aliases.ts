/**
 * Central alias map for settings fields: everyday vocabulary → field key.
 * Kept here (not on the field definitions) so search concerns stay inside
 * the search module. Every key MUST be a real field key — enforced by test.
 */
export const fieldAliases: Record<string, string[]> = {
    'system.grid.main_fuse_a': ['breaker', 'circuit breaker', 'fuse size', 'amps'],
    'system.grid.max_power_kw': ['import limit', 'grid limit'],
    'battery.min_soc_percent': ['battery floor', 'reserve', 'state of charge'],
    'battery.max_soc_percent': ['battery ceiling', 'state of charge'],
    'battery_economics.battery_cycle_cost_kwh': ['wear cost', 'degradation', 'battery wear'],
    'executor.override.low_soc_export_floor': ['backup reserve', 'export stop'],
    'water_heating.vacation_mode.enabled': ['away mode', 'holiday mode'],
    'input_sensors.vacation_mode': ['away mode', 'holiday mode'],
    'water_heating.vacation_mode.anti_legionella_temp_c': ['legionella', 'bacteria'],
    'executor.notifications.service': ['alerts', 'push notifications', 'messages'],
    'load_balancing.give_way_order': ['priority order', 'shedding order'],
    'load_balancing.enabled': ['breaker', 'fuse protection', 'overload'],
    'executor.excess_pv.priority': ['surplus solar', 'dump load', 'solar overflow'],
    'pricing.grid_transfer_fee_sek': ['network fee', 'transmission fee'],
    'nordpool.price_area': ['spot price', 'electricity price', 'bidding zone'],
    'advisor.enable_llm': ['ai', 'chatgpt', 'assistant'],
    'forecasting.pv_confidence_percent': ['solar trust', 'forecast confidence'],
}
