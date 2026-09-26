# Darkstar Design System — AI Guidelines

> **SSOT**: [`frontend/src/index.css`](file:///frontend/src/index.css)
> **Preview**: Run `pnpm run dev` and navigate to `/design-system`

---

## Color Usage

### Flair Colors (Same in Light/Dark Mode)
| Color | Variable | Use Case |
|-------|----------|----------|
| **Accent** (Gold) | `--color-accent` | Primary actions, highlights, active states |
| **Good** (Green) | `--color-good` | Success, positive values, profits |
| **Warn** (Amber) | `--color-warn` | Warnings, caution states |
| **Bad** (Red) | `--color-bad` | Errors, negative values, critical alerts |
| **Water** (Blue) | `--color-water` | Water heating related |
| **House** (Teal) | `--color-house` | House load, consumption |
| **Grid** (Slate) | `--color-grid` | Grid import/export |
| **Peak** (Pink) | `--color-peak` | Peak pricing periods |
| **Night** (Cyan) | `--color-night` | Night/off-peak periods |
| **AI** (Violet) | `--color-ai` | AI/smart features, automation |

### Surface Colors (Different per Theme)
| Color | Use |
|-------|-----|
| `--color-canvas` | Page background |
| `--color-surface` | Card/panel backgrounds |
| `--color-surface2` | Nested/secondary surfaces |
| `--color-line` | Borders, dividers |
| `--color-text` | Primary text |
| `--color-muted` | Secondary/helper text |

---

## Typography Rules

Use Tailwind classes:
- **Headings**: `text-4xl` (28px), `text-3xl` (24px), `text-2xl` (18px)
- **Body**: `text-lg` (14px), `text-base` (12px)
- **Small**: `text-sm` (11px), `text-xs` (10px)

Line-heights are built into the Tailwind config.

---

## Component Classes

### Buttons
```tsx
<button className="btn btn-primary">Primary</button>
<button className="btn btn-secondary">Secondary</button>
<button className="btn btn-danger">Danger</button>
<button className="btn btn-ghost">Ghost</button>
<button className="btn btn-primary btn-pill">Pill</button>
```

For dynamic colors (when color is a prop):
```tsx
<button
  className="btn btn-pill btn-dynamic"
  style={{ '--btn-bg': color, '--btn-text': textColor } as React.CSSProperties}
>
```

### Banners
```tsx
<div className="banner banner-info">Info message</div>
<div className="banner banner-success">Success</div>
<div className="banner banner-warning">Warning</div>
<div className="banner banner-error">Error</div>
<div className="banner banner-purple">Special (shadow mode)</div>
```

### Badges
```tsx
<span className="badge badge-good">Online</span>
<span className="badge badge-warn">Pending</span>
<span className="badge badge-bad">Offline</span>
<span className="badge badge-muted">N/A</span>
```

### Form Inputs
```tsx
<input type="text" className="input" placeholder="..." />
```

### SoC Stepper
Shared target selector for Top Up and EV Charge (`components/ui/SocStepper.tsx`, classes `.soc-stepper*`):
```tsx
<SocStepper value={target} min={minSoc} max={100} onChange={setTarget} label="Top Up target" />
```
− / + move 15 percentage points (clamped to min–max); tapping the value opens a number input (Enter/blur commits, Esc cancels, invalid input keeps the old value). Pure helpers `clampSoc` / `parseSocInput` live in `components/ui/socStepper.ts`. For other integer values pass `step` and `unit`, e.g. `step={1} unit="d"` for days. Inside a `.qa-popover` the stepper renders at touch size automatically.

### Quick Action (button + popover)
Command bar controls (`components/ui/QuickAction.tsx`, classes `.qa-*`). One button shows icon, label and current value; tapping opens a popover with the settings and a Start/Stop button. Below 640px the popover is a bottom sheet. Closes on ✕, Esc or an outside tap.
```tsx
<QuickAction label="Top Up" icon={BatteryCharging} tone="good" title="Battery Top Up" active={isActive} value="60%">
  {(close) => (
    <>
      <QuickActionSection label="Charge battery to">
        <QuickActionChips label="Top Up target" options={presets} value={target} onChange={setTarget} />
      </QuickActionSection>
      <button className="qa-submit" onClick={() => start().then(close)}>Start</button>
    </>
  )}
</QuickAction>
```
- `tone`: `accent` | `good` | `ai` | `water` | `warn` — drives border, text and the active fill.
- `active`: filled button with the tone colour; put the live status (target, countdown) in `value`.
- `.qa-submit` is the primary action; `data-variant="stop"` makes it the red Stop button.
- `.qa-select` for dropdowns, `.qa-levels` / `.qa-level` for a tap-to-apply list (Risk / Water levels).
- Touch targets: buttons, chips and rows are ≥ 44px high on mobile.

### Loading States
```tsx
<div className="spinner" />
<div className="skeleton h-8 w-full" />
<div className="progress-bar">
  <div className="progress-bar-fill" style={{ width: '65%' }} />
</div>
```

---

## Dark/Light Mode Patterns

- **Banners**: Solid background in light mode, semi-transparent with border in dark mode
- **Button glows**: Only visible in dark mode (`.dark .btn-primary { box-shadow: ... }`)
- **Grain texture**: 10% opacity in light, 3% in dark

The theme is controlled by adding/removing `.dark` class on `<html>`.

---

## DO ✅ / DON'T ❌

### ✅ DO
- Use design system classes: `.btn-primary`, `.banner-warning`, `.badge-good`
- Use color variables: `text-accent`, `bg-surface`, `border-line`
- Use spacing tokens: `p-ds-4`, `gap-ds-2`, `m-ds-6`
- Use radius tokens: `rounded-ds-md`, `rounded-ds-lg`

### ❌ DON'T
- Use hardcoded colors: `bg-[#FFCE59]` → use `bg-accent`
- Use random radii: `rounded-xl` → use `rounded-ds-lg`
- Use inline styles for static colors: `style={{ color: 'red' }}` → use `text-bad`
- Duplicate CSS: define new classes in components → add to `index.css`

---

## Metric Cards

Fat left border pattern:
```tsx
<div className="metric-card-border metric-card-border-solar bg-surface p-4">
  <div className="text-xs text-muted uppercase">Solar</div>
  <div className="text-2xl font-bold text-text">4.2 kW</div>
</div>
```

Available borders: `solar`, `battery`, `house`, `water`, `grid`, `bad`

---

## Adding New Components

1. Define the CSS class in `frontend/src/index.css` under `@layer components`
2. Add showcase to `frontend/src/pages/DesignSystem.tsx`
3. Update this document
4. Commit with message: `feat(design): add [component name] component`
