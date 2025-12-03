// This code is for an n8n "Code" node.
// Place this node AFTER the node that fetches the Nordpool sensor state.
// Make sure the output of your "Calculate Slot" node is available (e.g., via Merge or direct reference).

// 1. Get the target slot timestamp from your calculation node
// IMPORTANT: Replace 'Calculate Completed Slot' with the exact name of your first node!
// We use .first() because the slot calculation usually runs once per execution.
const targetSlotIso = $('Calculate Completed Slot').first().json.slot_start_ts;

// 2. Get the Nordpool attributes from the current input item
const attributes = items[0].json.attributes;
const rawToday = attributes.raw_today || [];
const rawTomorrow = attributes.raw_tomorrow || [];

// 3. Combine lists to search (Today + Tomorrow covers midnight crossings)
const allPrices = rawToday.concat(rawTomorrow);

// 4. Find the exact match
// The 'start' field in raw_today is an ISO string like "2025-12-03T00:00:00+01:00"
// targetSlotIso might have milliseconds like "2025-12-03T00:00:00.000+01:00"
let matchedPrice = null;
let source = "fallback_state";

const match = allPrices.find(entry => {
    // Normalize both by removing milliseconds (if any) before the timezone
    // Regex: remove . followed by 3 digits
    const entryNorm = entry.start.replace(/\.\d{3}/, '');
    const targetNorm = targetSlotIso.replace(/\.\d{3}/, '');
    return entryNorm === targetNorm;
});

if (match) {
    matchedPrice = match.value;
    source = "15min_attribute";
} else {
    // Fallback: If no match found, use the main state (though it might be hourly)
    matchedPrice = parseFloat(items[0].json.state);
}

// 5. Output the result
return [
    {
        json: {
            // This is the correct 15-minute price
            import_price: matchedPrice,

            // Debug info
            price_source: source,
            slot_target: targetSlotIso,
            matched_entry: match, // <--- Added this to see what we matched!

            // Pass through other useful info if needed
            ...items[0].json
        }
    }
];
