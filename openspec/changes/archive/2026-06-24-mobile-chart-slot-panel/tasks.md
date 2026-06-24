## 1. Disable mobile floating tooltip

- [x] 1.1 Configure Chart.js tooltip to be disabled on viewports < 768 px in `ChartCard.tsx`
- [x] 1.2 Confirm desktop (≥ 768 px) tooltip config is unchanged

## 2. Slot selection and vertical band

- [x] 2.1 Add tap handler on the chart canvas that resolves the nearest slot index on mobile
- [x] 2.2 Implement Chart.js `afterDraw` plugin that draws the full-height vertical selection band with amber accent line at the selected slot index
- [x] 2.3 Clear selection state when chart data refreshes

## 3. Inset slot values panel

- [x] 3.1 Add inset panel component/section below the chart timeline in `ChartCard`
- [x] 3.2 Render time heading and each visible series' formatted value (including spot + tax/fees breakdown) for the selected slot
- [x] 3.3 Show/hide panel and expand/collapse card height based on selection state

## 4. Outside-tap dismissal and viewport cleanup

- [x] 4.1 Attach document-level click listener that clears selection when tap target is outside the card
- [x] 4.2 Clear selection when viewport crosses from mobile to desktop (resize/breakpoint change)
- [x] 4.3 Remove event listeners on component unmount

## 5. Documentation

- [x] 5.1 Add `dashboard-layout` delta spec with Mobile chart slot selection panel requirement and scenarios
