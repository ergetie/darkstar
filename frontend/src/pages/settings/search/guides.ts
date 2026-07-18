export interface Guide {
    id: string
    title: string
    summary: string
    body: string
    relatedFieldKeys: string[]
    /** Alternative search terms (everyday vocabulary) that should find this guide. */
    aliases?: string[]
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
        aliases: ['breaker', 'circuit breaker', 'overload protection', 'phases'],
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
        aliases: ['car', 'car charging', 'wallbox', 'electric vehicle'],
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

Vacation Mode reduces how much the water heater is used while you're away, but still runs a periodic safety cycle (anti-legionella) at a set temperature, interval, and duration to keep the tank safe even when it's not being used normally. See the Vacation Mode guide for the full picture.`,
        aliases: ['hot water', 'boiler', 'tank', 'heating'],
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

The S-Index is a separate safety mechanism that keeps back extra battery reserve on days when things look riskier than normal — for example, very cold weather (which increases heating load) or when the solar forecast is unreliable. It has two modes: "Probabilistic," which reserves extra buffer based on a statistical worst-case forecast, and "Dynamic," which adapts the reserve continuously based on recent conditions. The temperature and horizon settings tune how aggressively it reacts to cold weather and how many days ahead it looks.

For how the planner decides when cycling the battery is actually worth it, see the Arbitrage & Economics guide.`,
        aliases: ['state of charge', 'soc', 'safety reserve'],
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

When solar production exceeds what the house and battery need, the excess has to go somewhere — that's what the Excess PV Dispatch priority list (on the Advanced tab) controls. It's an ordered list of "sinks" (like the water heater or EV charger) that surplus solar gets routed into instead of being exported for a lower price, with the battery always implicitly first in line. The SoC threshold controls how full the battery needs to be before any of those sinks kick in, so you don't skip charging the battery to dump power into a lower-priority sink. The Excess PV Dispatch guide covers this in more depth.`,
        aliases: ['pv', 'panels', 'sun', 'production forecast'],
        relatedFieldKeys: [
            'system.location.latitude',
            'system.location.longitude',
            'system.solar_arrays',
            'forecasting.pv_confidence_percent',
            'executor.excess_pv.priority',
            'executor.excess_pv.soc_threshold_percent',
        ],
    },
    {
        id: 'planner-executor',
        title: 'Guide: Planner & Executor Basics',
        summary: 'How Darkstar actually works: the planner makes a schedule, the executor carries it out.',
        body: `Darkstar has two halves that work together. The planner looks at electricity prices, your solar and load forecasts, and your settings, then solves for the cheapest safe schedule for the day ahead — when to charge the battery, when to heat water, when to charge the car. The executor then carries that schedule out, tick by tick, by controlling your devices through Home Assistant.

The planner re-plans on a regular interval (the Planner Interval, e.g. every 30 minutes) as long as the background scheduler is enabled, so the schedule keeps adapting to new prices and forecasts. You can also run it manually at any time with the "Run Planner" button on the dashboard. The executor ticks much more often (the Executor Interval, a few seconds to a few minutes) — each tick it checks what the schedule says should be happening right now and adjusts the devices accordingly.

Pausing (the Pause button on the dashboard command bar) stops the executor from making changes — nothing is controlled until you press Resume. If a schedule is too old (for example the planner hasn't been able to run for several hours), the executor refuses to act on it and holds safe instead of executing a stale plan.

There's also a manual override: if the configured override toggle is on in Home Assistant, Darkstar keeps its hands off your devices entirely while continuing to record data. Useful when you want to control things by hand for a while.`,
        aliases: ['how it works', 'schedule', 'optimizer', 'automation', 'intervals'],
        relatedFieldKeys: [
            'automation.enable_scheduler',
            'automation.schedule.every_minutes',
            'executor.interval_seconds',
            'executor.manual_override_entity',
            'executor.automation_toggle_entity',
        ],
    },
    {
        id: 'quick-actions',
        title: 'Guide: Quick Actions & Command Bar',
        summary: 'The dashboard command bar: pause/resume, Top Up, Water Boost, and the vacation toggle.',
        body: `The command bar at the top of the dashboard gives you direct control without touching any settings.

Run Planner triggers a fresh plan immediately, with progress shown inline. The Auto toggle turns the background scheduler on or off — with it off, Darkstar only plans when you ask it to.

Pause stops the executor from controlling anything; the button turns into a red pulsing Resume so you can't miss that the system is idle.

Top Up force-charges the battery to a target you pick (30, 50, 80, or 100%) for the next hour — useful before a storm or an expensive evening. While it's active the button shows STOP, and clicking again cancels it.

Boost heats your water to the boost temperature right now, for a duration you pick (30 minutes, 1 hour, or 2 hours), with a countdown while it runs. The boost automatically cancels if the battery gets too low, so comfort never drains your reserve.

Vacay turns on Vacation Mode for a number of days you pick (1 to 30) and turns itself off automatically when that period ends.

The Risk and Water comfort selectors (levels 1–5) tune how boldly the planner chases savings versus how much safety margin and hot-water comfort it keeps. They take effect at the next planning run.`,
        aliases: ['buttons', 'pause', 'resume', 'boost', 'top up', 'force charge', 'manual control'],
        relatedFieldKeys: [
            'automation.enable_scheduler',
            'executor.water_heater.temp_boost',
            'water_heating.vacation_mode.enabled',
            'battery.min_soc_percent',
        ],
    },
    {
        id: 'vacation-mode',
        title: 'Guide: Vacation Mode',
        summary: 'What changes while you are away, and how the tank stays safe with the anti-legionella cycle.',
        body: `Vacation Mode tells Darkstar nobody is home. Its main effect is on water heating: the usual daily minimums are dropped to zero, so the tank isn't kept hot for no one. Everything else (battery optimization, solar, load balancing) keeps running as normal.

Even with heating effectively off, the tank can't just be left cold indefinitely — standing lukewarm water is where legionella bacteria grow. The anti-legionella safety cycle handles this: at a set interval (e.g. every few days) the heater runs for a set duration at a set high temperature, killing anything growing in the tank. The three safety-cycle settings control that temperature, interval, and duration.

You can activate Vacation Mode three ways: the Vacay button on the dashboard command bar (pick 1–30 days; it turns itself off when the period ends), the toggle here in Settings, or — if configured — a Home Assistant entity (like an input boolean tied to your alarm or presence detection), which Darkstar follows live.

Vacation state also feeds the load forecasting, so the system learns that away-days look different from normal days.`,
        aliases: ['away mode', 'holiday', 'travel', 'legionella', 'away'],
        relatedFieldKeys: [
            'water_heating.vacation_mode.enabled',
            'water_heating.vacation_mode.anti_legionella_temp_c',
            'water_heating.vacation_mode.anti_legionella_interval_days',
            'water_heating.vacation_mode.anti_legionella_duration_hours',
            'input_sensors.vacation_mode',
        ],
    },
    {
        id: 'notifications',
        title: 'Guide: Notifications & Alerts',
        summary: 'Getting told what Darkstar is doing, via Home Assistant notifications.',
        body: `Darkstar can notify you when it acts, using any Home Assistant notify service — typically the mobile app on your phone (e.g. notify.mobile_app_your_phone). Set the service once, then choose which events you care about with the per-event toggles: battery charging starting or stopping, grid export starting or stopping, water heating starting or stopping, SoC target changes, a manual override activating, and errors.

Load balancer interventions have their own separate toggle, since fuse-protection events are the kind of thing you may want to know about even if you've muted the routine ones.

If you're looking for "price alerts" — a heads-up about unusually cheap or expensive hours coming up — those aren't sent as notifications. They appear in the Advisor card on the dashboard, based on the price forecast (see the AI Advisor guide).`,
        aliases: ['alerts', 'push', 'phone', 'notify', 'messages'],
        relatedFieldKeys: [
            'executor.notifications.service',
            'executor.notifications.on_charge_start',
            'executor.notifications.on_export_start',
            'executor.notifications.on_water_heat_start',
            'executor.notifications.on_error',
            'load_balancing.notify_interventions',
        ],
    },
    {
        id: 'ai-advisor',
        title: 'Guide: AI Advisor',
        summary: 'The dashboard advisor card: plan summaries, price alerts, and optional AI-written advice.',
        body: `The Advisor card on the dashboard explains what the system is planning and why, in plain language. It shows a summary of today's plan (when the battery will charge, discharge, or export), plus price alerts — notable things in the upcoming prices, like an unusually cheap day ahead or a cheap overnight window (these need price forecasting to be enabled).

With "Enable LLM advice" on, the advice text is written by an AI language model, and you can pick its personality: Concise (money focus), Friendly (emoji style), or Technical (data heavy). With it off, you still get advice — a built-in rule-based analyst generates recommendations instead, no AI involved.

The advisor only reads data the system already has (your plan, prices, forecasts, and current state like vacation mode) to write its advice — it doesn't control anything, and it can't change settings.

Auto-fetch controls whether fresh advice is fetched automatically when you open the dashboard or the schedule changes; otherwise use the refresh button on the card.`,
        aliases: ['llm', 'ai', 'advice', 'recommendations', 'price alerts', 'assistant'],
        relatedFieldKeys: ['advisor.enable_llm', 'advisor.auto_fetch', 'advisor.personality', 'price_forecast.enabled'],
    },
    {
        id: 'excess-pv-dispatch',
        title: 'Guide: Excess PV Dispatch',
        summary: 'Where surplus solar goes when the house is fed and the battery is full.',
        body: `On a good solar day there's a point where your panels produce more than the house is using and the battery is (nearly) full. That surplus has to go somewhere, and exporting it earns only the raw spot price — often less than the energy is worth to you. Excess PV Dispatch routes it into "sinks" of your choosing instead.

The sink priority list (on the Advanced tab) is ordered: the first entry gets surplus first. Available sinks are EV surplus charging, a water heater boost, and a custom Home Assistant entity (for example a pool pump — you tell Darkstar its entity, on/off values, and power draw). The house battery is always implicitly first in line before any sink. If the list is empty, the feature is off entirely.

Two settings tune the behavior. The SoC Threshold (default 95%) is how full the battery must be projected to be before sinks activate — so you never skip charging the battery to dump power into a lower-priority sink. The Base Reward is the value the planner assigns to feeding a sink, per kWh: if the export price is higher than that reward, exporting wins; if lower, the sink wins. Lower-ranked sinks get a slightly reduced reward, which is what makes the ordering matter.

When there's only a little surplus, it all goes to the top sink; when there's plenty, several sinks can be fed at once.`,
        aliases: ['surplus solar', 'dump load', 'pool pump', 'solar overflow', 'sinks'],
        relatedFieldKeys: [
            'executor.excess_pv.priority',
            'executor.excess_pv.soc_threshold_percent',
            'executor.excess_pv.boost_reward_sek_per_kwh',
            'export.enable_export',
        ],
    },
    {
        id: 'aurora-ml',
        title: 'Guide: Aurora (ML Forecasting)',
        summary: 'The machine-learning layer that personalizes load and solar forecasts to your home.',
        body: `Aurora is Darkstar's machine-learning forecasting system. Instead of relying only on generic profiles and weather models, it learns from your home's actual history — when your household uses power, and how your particular panels really perform — and uses that to sharpen the forecasts the planner works from.

It has two independent halves, each with its own toggle on the Aurora page. Load forecasting predicts your household consumption; switched off, Darkstar falls back to a simpler profile learned from Home Assistant history. PV forecasting adds a personal correction on top of the physics-based weather forecast (from Open-Meteo); switched off, the physics forecast is used as-is. The correction is deliberately bounded and phased in gradually as the model earns trust, so a young or confused model can't distort the forecast much.

The Aurora page also shows when the models were last trained and how accurate they've been recently. Models retrain automatically on fresh data, with recent days weighted more heavily than old ones.

The Reflex loop (on the Advanced tab) is a related learning feature: it makes small automatic adjustments to planner parameters based on how well previous plans actually turned out, within strict daily limits you can see under Learning Parameter Limits.`,
        aliases: ['machine learning', 'ml', 'training', 'model', 'predictions', 'reflex'],
        relatedFieldKeys: [
            'learning.reflex_enabled',
            'forecasting.pv_confidence_percent',
            'forecasting.load_safety_margin_percent',
            'learning.min_sample_threshold',
        ],
    },
    {
        id: 'arbitrage-economics',
        title: 'Guide: Arbitrage & Economics',
        summary: 'How Darkstar decides when charging, discharging, or exporting is actually worth the money.',
        body: `Every decision the planner makes is economic: it compares what energy costs now against what it will cost later, and only acts when the difference is worth it.

What you pay for a kWh is more than the spot price: VAT, the grid transfer fee, and energy tax come on top (configured under Pricing & Timezone). What you earn for an exported kWh is just the raw spot price — no fees, no VAT. That asymmetry is why exporting is usually the last choice, after using the energy yourself.

Battery arbitrage — charging cheap to use or sell expensive — has a real cost: wear on the battery. The battery cycle cost setting puts a price on that wear per kWh cycled, and the planner never treats cycling as free. On top of that, exports must clear a dynamic profit threshold before the planner bothers: when daily prices are flat the bar is high, and it comes down as the day's price spread grows (how far down depends on your risk level). This stops the battery from micro-cycling for pennies.

Two advanced knobs shape the economics further: the curtailment penalty makes wasting producible solar expensive to the planner (so it prefers any revenue-positive use over throttling the panels — though when export prices go negative, curtailing is exactly right), and the ramping cost discourages rapid power swings.

Grid export as a whole is gated by the "Enable grid export" toggle, and the Export Prevention Floor stops export below a chosen battery level so arbitrage never eats your backup reserve.`,
        aliases: ['profit', 'money', 'savings', 'export price', 'fees', 'taxes', 'buy low sell high'],
        relatedFieldKeys: [
            'export.enable_export',
            'battery_economics.battery_cycle_cost_kwh',
            'pricing.vat_percent',
            'pricing.grid_transfer_fee_sek',
            'pricing.energy_tax_sek',
            'kepler.curtailment_penalty_sek',
            'kepler.ramping_cost_sek_per_kw',
            'executor.override.low_soc_export_floor',
        ],
    },
    {
        id: 'getting-started',
        title: 'Guide: Getting Started & HA Connection',
        summary: 'What Darkstar needs from Home Assistant, and why features stay hidden until it gets it.',
        body: `Darkstar doesn't talk to your hardware directly — everything goes through Home Assistant. It needs three kinds of things configured: a connection, sensors to see with, and control entities to act with.

The connection is the Home Assistant URL and a long-lived access token. On a fresh install, the startup wizard walks you through the essentials: picking your inverter profile (which pre-fills the standard entity names for that brand), entering your battery and solar specs, and establishing a baseline consumption profile from your history.

Sensors are how Darkstar sees your home: at minimum, load power and grid power (either one net meter, or separate import/export sensors — the Grid Meter Type setting picks which). The "Lifetime Energy Totals" sensors (cumulative kWh counters) feed the energy statistics. Control entities are how it acts: the inverter's charge/discharge limits, work mode, SoC target, and grid charging switch.

A core principle: features fail safe by staying off until fully configured. The system profile toggles (solar, battery, water heater, EV) hide whole tabs and features you don't have. Load balancing stays inert until the main fuse, all three phase sensors, and a give-way order are set. If you search for a setting and it's marked hidden or disabled, the hint tells you what's missing — that's the fastest way to find out why a feature is greyed out.`,
        aliases: ['setup', 'installation', 'wizard', 'onboarding', 'connect', 'greyed out', 'entities'],
        relatedFieldKeys: [
            'home_assistant.url',
            'home_assistant.token',
            'system.inverter_profile',
            'system.grid_meter_type',
            'input_sensors.load_power',
            'input_sensors.grid_power',
            'executor.inverter.work_mode',
            'executor.inverter.soc_target',
        ],
    },
]
