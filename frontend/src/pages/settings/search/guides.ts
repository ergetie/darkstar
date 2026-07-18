export interface Guide {
    id: string
    title: string
    summary: string
    body: string
    relatedFieldKeys: string[]
}

export const guides: Guide[] = [
    {
        id: 'load-balancing',
        title: 'Guide: Load Balancing',
        summary:
            'Keeps your main fuse from tripping by throttling the EV charger, and sheds other loads as a last resort.',
        body: `Load balancing watches how much current is flowing on each of your three grid phases and steps in before your main fuse trips. If a phase gets close to its limit, it first slows down EV charging on that phase. If that's not enough, it starts shedding other loads in an order you control, and brings them back on in reverse order once things settle down.

It stays completely switched off until three things are configured: the main fuse rating, a current or power sensor for all three phases, and at least one load in the give-way order. Until all of those are set, the feature does nothing — it's designed to fail safe.

The main fuse rating is the physical amp rating of your fuse (e.g. 20A per phase) — this is different from your overall grid import limit, because a balanced total power draw can still overload a single phase.

The give-way order is the list of things the balancer is allowed to act on, ranked by your preference. The top entry gives way first when a phase overloads (e.g. slow down the EV charger before shedding the water heater), and things come back in the exact reverse order once the phase has headroom again.

The anti-flap settings (resume delay, resume margin, ramp-up step, stale-sensor timeout) control how cautiously the balancer resumes or ramps back up — they exist so a noisy sensor reading doesn't cause the system to flicker loads on and off.

This is a software safety net, not a certified protection device. If your EV charger has its own built-in load-management setting, keep that enabled too as a backup.`,
        relatedFieldKeys: [
            'load_balancing.enabled',
            'system.grid.main_fuse_a',
            'input_sensors.grid_current_l1',
            'load_balancing.give_way_order',
            'load_balancing.resume_delay_s',
            'load_balancing.resume_margin_percent',
            'load_balancing.sensor_stale_after_s',
        ],
    },
    {
        id: 'ev-charging',
        title: 'Guide: EV Charging',
        summary: 'How your EV chargers are configured for smart, optimized charging.',
        body: `Darkstar can manage one or more EV chargers, scheduling their charging around cheap electricity prices and available solar power instead of just charging at full speed whenever plugged in.

Each charger you add needs a unique ID, a friendly name, its maximum power rating, and a sensor that reports how much power it's currently drawing. This lets the planner know exactly how much of your total load is the car, separate from everything else in the house (this is called "load disaggregation").

Once a charger is configured, two other things become available:
- The Load Balancing tab appears, so the charger's current can be automatically throttled if your main fuse is at risk of overloading.
- The EV charger can be included in the give-way order, so it's one of the things that slows down (or speeds back up) as part of load balancing.

If you also have solar, excess PV can be prioritized towards EV charging before it's exported to the grid, depending on how your excess-PV sink priority is set up on the Advanced tab.`,
        relatedFieldKeys: ['ev_chargers', 'load_balancing.enabled', 'load_balancing.give_way_order'],
    },
    {
        id: 'water-heater',
        title: 'Guide: Water Heater',
        summary:
            'How smart water heating schedules heating around price and solar, while keeping water safe and hot when you need it.',
        body: `Water heating is one of the biggest loads in most homes, and one of the most flexible — hot water doesn't need to be reheated the instant it cools a little. Darkstar uses that flexibility to shift heating towards cheap electricity or free solar power.

Each water heater you add needs a unique ID, name, power rating, and sensor. Multiple heaters can be configured and optimized independently.

The temperature setpoints control how the heater behaves in different modes:
- Off/Idle: the minimum safe temperature when not actively heating (this exists for legionella safety, so it won't go below a safe floor).
- Normal: the target for regular scheduled heating.
- Boost: a higher target for manual "I need hot water now" boost/spa mode.
- Max/PV Dump: the ceiling temperature used when dumping excess solar power into the tank — it won't heat past this even with free surplus solar.

The scheduling settings control how much the planner can shift things around: "max defer hours" lets it push today's heating into the early hours of tomorrow if that's cheaper, and "spaced top-ups" lets it do several small heating bursts through the day to maintain temperature, instead of one large block.

Vacation Mode reduces how much the water heater is used while you're away, but still runs a periodic safety cycle (anti-legionella) at a set temperature, interval, and duration to keep the tank safe even when it's not being used normally.`,
        relatedFieldKeys: [
            'water_heaters',
            'water_heating.defer_up_to_hours',
            'water_heating.enable_top_ups',
            'executor.water_heater.temp_normal',
            'executor.water_heater.temp_boost',
            'executor.water_heater.temp_max',
            'water_heating.vacation_mode.enabled',
        ],
    },
    {
        id: 'battery-s-index',
        title: 'Guide: Battery & S-Index',
        summary:
            'How your battery is configured and how the S-Index keeps a safety reserve for cold or uncertain days.',
        body: `Your battery settings define the safe operating envelope the planner works within: total usable capacity, max charge/discharge power, and the state-of-charge (SoC) range it's allowed to use. Min SoC and Max SoC are soft preferences the planner tries to respect (your battery's own management system enforces the hard safety limits underneath).

The Export Prevention Floor is a separate safety setting: it stops the battery from exporting to the grid once it drops below that SoC, so you don't accidentally drain your backup reserve just to make a bit of money on export.

Battery cycle cost estimates the wear-and-tear cost of charging and discharging the battery, in money per kWh cycled. The planner weighs this against potential arbitrage profit — a higher cycle cost makes the planner more conservative about cycling the battery just to chase small price differences.

The S-Index is a separate safety mechanism that keeps back extra battery reserve on days when things look riskier than normal — for example, very cold weather (which increases heating load) or when the solar forecast is unreliable. It has two modes: "Probabilistic," which reserves extra buffer based on a statistical worst-case forecast, and "Dynamic," which adapts the reserve continuously based on recent conditions. The temperature and horizon settings tune how aggressively it reacts to cold weather and how many days ahead it looks.`,
        relatedFieldKeys: [
            'battery.capacity_kwh',
            'battery.min_soc_percent',
            'battery.max_soc_percent',
            'executor.override.low_soc_export_floor',
            'battery_economics.battery_cycle_cost_kwh',
            's_index.mode',
            's_index.temp_cold_c',
        ],
    },
    {
        id: 'solar-forecast',
        title: 'Guide: Solar Forecast',
        summary: 'How Darkstar predicts your solar production and decides what to do with excess power.',
        body: `Darkstar forecasts how much solar power your panels will produce using your location and the layout of your solar arrays. Getting the latitude, longitude, and array details (orientation, tilt, and peak power) right directly improves how accurate that forecast is, which in turn improves every scheduling decision the planner makes.

You can configure up to six separate arrays if your panels face different directions (e.g. some east-facing, some west-facing) — each is forecast independently and combined into a total.

PV Confidence controls how much the planner trusts the forecast: at 100%, it plans as if the forecast will come true exactly; lower values make the planner hedge, assuming less solar will actually show up, which is safer but can leave some potential savings on the table.

When solar production exceeds what the house and battery need, the excess has to go somewhere — that's what the Excess PV Dispatch priority list (on the Advanced tab) controls. It's an ordered list of "sinks" (like the water heater or EV charger) that surplus solar gets routed into instead of being exported for a lower price, with the battery always implicitly first in line. The SoC threshold controls how full the battery needs to be before any of those sinks kick in, so you don't skip charging the battery to dump power into a lower-priority sink.`,
        relatedFieldKeys: [
            'system.location.latitude',
            'system.location.longitude',
            'system.solar_arrays',
            'forecasting.pv_confidence_percent',
            'executor.excess_pv.priority',
            'executor.excess_pv.soc_threshold_percent',
        ],
    },
]
