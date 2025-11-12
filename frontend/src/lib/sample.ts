export const sampleChart = {
    labels: Array.from({length: 24}, (_,i) => `${String(i).padStart(2,'0')}:00`),
    load: Array.from({length: 24}, () => +(Math.random()*2.2+0.6).toFixed(2)),
    pv: Array.from({length: 24}, (__,i) => +(Math.max(0, Math.sin((i-6)/4))*2.4).toFixed(2)),
    price: Array.from({length: 24}, () => +(Math.random()*3.2+0.8).toFixed(2)),
}

/** Mock lanes for Planning */
export const lanes = [
    { id: 'battery', label: 'Battery', color: '#AAB6C4' },
{ id: 'water',   label: 'Water',   color: '#FF7A7A' },
{ id: 'export',  label: 'Export',  color: '#9BF6A3' },
{ id: 'hold',    label: 'Hold',    color: '#FFD966' },
]

export const blocks = [
    // start hour, length hours, lane id
    { lane: 'hold', start: 0, len: 15.5, color: '#FFD966' },
{ lane: 'hold', start: 17.5, len: 2.5, color: '#FFD966' },
{ lane: 'hold', start: 5, len: 1.4, color: '#FFD966' },

{ lane: 'battery', start: 22.4, len: 2.3, color: '#AAB6C4' },
{ lane: 'water',   start: 23.0, len: 1.5, color: '#FF7A7A' },
]
