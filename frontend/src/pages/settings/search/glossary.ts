export interface GlossaryEntry {
    id: string
    term: string
    definition: string
    /** Alternative search terms (everyday vocabulary) that should find this entry. */
    aliases?: string[]
    relatedFieldKeys?: string[]
    relatedGuideIds?: string[]
}

export const glossaryEntries: GlossaryEntry[] = [
    {
        id: 'soc',
        term: 'SoC (State of Charge)',
        definition: `How full your battery is, as a percentage — 0% is empty, 100% is full. Almost every battery decision in Darkstar is expressed in SoC: the Min/Max SoC settings define the range the planner is allowed to use, the Export Prevention Floor stops grid export below a certain SoC, and the S-Index reserves extra SoC on risky days. Your battery's own management system enforces its hard safety limits underneath whatever Darkstar asks for.`,
        aliases: ['state of charge', 'battery level', 'battery percentage'],
        relatedFieldKeys: ['battery.min_soc_percent', 'battery.max_soc_percent', 'input_sensors.battery_soc'],
        relatedGuideIds: ['battery-s-index'],
    },
    {
        id: 's-index',
        term: 'S-Index',
        definition: `Darkstar's safety index — a mechanism that keeps back extra battery reserve on days that look riskier than normal, for example very cold weather (more heating load) or an unreliable solar forecast. A higher S-Index means a bigger safety buffer and less battery available for savings. It runs in either Probabilistic mode (statistical worst-case) or Dynamic mode (continuously adapting).`,
        aliases: ['safety index', 'safety reserve', 'safety buffer'],
        relatedFieldKeys: ['s_index.mode', 's_index.temp_cold_c', 's_index.s_index_horizon_days'],
        relatedGuideIds: ['battery-s-index'],
    },
    {
        id: 'arbitrage',
        term: 'Arbitrage',
        definition: `Buying electricity when it's cheap, storing it in the battery, and using it (or selling it back) when prices are high — profiting from the price difference. The planner constantly weighs arbitrage opportunities against the wear-and-tear cost of cycling the battery: if the price gap is smaller than the cycle cost, it leaves the battery alone.`,
        aliases: ['price trading', 'buy low sell high'],
        relatedFieldKeys: ['battery_economics.battery_cycle_cost_kwh', 'export.enable_export'],
        relatedGuideIds: ['arbitrage-economics', 'battery-s-index'],
    },
    {
        id: 'give-way',
        term: 'Give-Way Order',
        definition: `The ranked list of loads that load balancing is allowed to act on when a phase gets close to overloading your main fuse. The top entry gives way first (for example, the EV charger slows down before the water heater is shed), and loads come back in exact reverse order once the phase has headroom again.`,
        aliases: ['load priority', 'shedding order'],
        relatedFieldKeys: ['load_balancing.give_way_order'],
        relatedGuideIds: ['load-balancing'],
    },
    {
        id: 'curtailment',
        term: 'Curtailment',
        definition: `Deliberately producing less solar power than your panels could, usually because exporting it would lose money (for example when spot prices go negative). The curtailment penalty setting tells the planner how bad it should consider wasted solar potential — a higher penalty makes it try harder to use the energy somewhere instead of throttling production.`,
        aliases: ['solar throttling', 'wasted solar', 'negative prices'],
        relatedFieldKeys: ['kepler.curtailment_penalty_sek'],
        relatedGuideIds: ['solar-forecast', 'arbitrage-economics'],
    },
    {
        id: 'load-disaggregation',
        term: 'Load Disaggregation',
        definition: `Splitting your home's total power consumption into its parts — how much is the EV charger, how much is the water heater, and how much is everything else. Darkstar does this using each device's own power sensor. It matters because the planner can shift the EV and water heater in time, but must treat the rest of the house as a fixed load it has to forecast.`,
        aliases: ['load separation', 'baseline load', 'house load'],
        relatedFieldKeys: ['ev_chargers', 'water_heaters', 'input_sensors.load_power'],
        relatedGuideIds: ['ev-charging', 'water-heater'],
    },
    {
        id: 'spot-price',
        term: 'Spot Price (Nordpool)',
        definition: `The hourly wholesale electricity price set on the Nordpool power exchange for your price area. It's the raw market price — what you actually pay on top of it includes VAT, grid transfer fees, and energy tax, which you configure under Pricing. Export compensation, on the other hand, is based on the pure spot price without those add-ons, which is why exporting usually earns less per kWh than importing costs.`,
        aliases: ['electricity price', 'hourly price', 'nordpool price'],
        relatedFieldKeys: [
            'nordpool.price_area',
            'pricing.vat_percent',
            'pricing.grid_transfer_fee_sek',
            'pricing.energy_tax_sek',
        ],
        relatedGuideIds: ['arbitrage-economics'],
    },
    {
        id: 'excess-pv',
        term: 'Excess PV (Surplus Solar)',
        definition: `Solar production beyond what your house is consuming and your battery can absorb at that moment. It has to go somewhere: Darkstar routes it into the sinks you've prioritized (like the water heater or EV charger) before letting it export to the grid at the lower spot price.`,
        aliases: ['surplus solar', 'solar overflow', 'pv surplus'],
        relatedFieldKeys: ['executor.excess_pv.priority', 'executor.excess_pv.soc_threshold_percent'],
        relatedGuideIds: ['excess-pv-dispatch', 'solar-forecast'],
    },
]
