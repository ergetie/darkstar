import { useRef, useState, WheelEvent } from 'react'
import Timeline from 'react-calendar-timeline'
import 'react-calendar-timeline/dist/style.css'

type LaneId = 'battery' | 'water' | 'export' | 'hold'

type PlanningLane = {
  id: LaneId
  label: string
  color: string
}

type PlanningBlock = {
  id: string
  lane: LaneId
  start: Date
  end: Date
  source: 'schedule'
  isHistorical?: boolean
}

type PlanningTimelineProps = {
  lanes: PlanningLane[]
  blocks: PlanningBlock[]
  selectedBlockId?: string | null
  onBlockMove?: (args: { id: string; start: Date; lane: LaneId }) => void
  onBlockResize?: (args: { id: string; start: Date; end: Date }) => void
  onBlockSelect?: (id: string | null) => void
  onAddBlock?: (lane: LaneId) => void
}

export default function PlanningTimeline({
  lanes,
  blocks,
  selectedBlockId,
  onBlockMove,
  onBlockResize,
  onBlockSelect,
  onAddBlock,
}: PlanningTimelineProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const groups = lanes.map((lane) => ({
    id: lane.id,
    title: lane.label,
  }))

  const items = blocks.map((b) => ({
    id: b.id,
    group: b.lane,
    title: '',
    start_time: b.start,
    end_time: b.end,
    canMove: !b.isHistorical,
    canResize: b.isHistorical ? false : 'both',
    canChangeGroup: !b.isHistorical,
    className: `ds-timeline-item ds-timeline-${b.lane}${
      b.isHistorical ? ' ds-timeline-item-historical' : ''
    }${selectedBlockId === b.id ? ' ds-timeline-item-selected' : ''}`,
  }))

  const now = new Date()
  const baseStart = new Date(now)
  baseStart.setHours(0, 0, 0, 0)
  const baseEnd = new Date(baseStart.getTime() + 48 * 60 * 60 * 1000)

  const [visibleStart, setVisibleStart] = useState(baseStart.getTime())
  const [visibleEnd, setVisibleEnd] = useState(baseEnd.getTime())

  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault()
    const baseStartMs = baseStart.getTime()
    const baseEndMs = baseEnd.getTime()
    const baseSpan = baseEndMs - baseStartMs

    const currentSpan = visibleEnd - visibleStart
    const zoomDirection = event.deltaY < 0 ? 'in' : 'out'
    const zoomFactor = 0.15

    let newSpan =
      zoomDirection === 'in'
        ? currentSpan * (1 - zoomFactor)
        : currentSpan * (1 + zoomFactor)

    const minSpan = baseSpan * 0.05 // do not zoom in beyond ~2.4h
    if (newSpan < minSpan) newSpan = minSpan
    if (newSpan > baseSpan) newSpan = baseSpan

    // Zoom around mouse position horizontally
    let centerRatio = 0.5
    const container = containerRef.current
    if (container) {
      const rect = container.getBoundingClientRect()
      if (rect.width > 0) {
        const x = event.clientX - rect.left
        centerRatio = Math.min(1, Math.max(0, x / rect.width))
      }
    }

    const currentCenter = visibleStart + currentSpan * centerRatio
    let newStart = currentCenter - newSpan * centerRatio
    let newEnd = newStart + newSpan

    // Clamp to base window
    if (newStart < baseStartMs) {
      newStart = baseStartMs
      newEnd = newStart + newSpan
    }
    if (newEnd > baseEndMs) {
      newEnd = baseEndMs
      newStart = newEnd - newSpan
    }

    setVisibleStart(newStart)
    setVisibleEnd(newEnd)
  }

  return (
    <div className="relative">
      <div
        ref={containerRef}
        onWheel={handleWheel}
        className="relative"
      >
        <Timeline
        groups={groups}
        items={items}
        visibleTimeStart={visibleStart}
        visibleTimeEnd={visibleEnd}
        defaultTimeStart={baseStart}
        defaultTimeEnd={baseEnd}
        lineHeight={64}
        sidebarWidth={96}
        canMove
        canResize="both"
        canChangeGroup
        groupRenderer={({ group }) => {
          const lane = lanes.find(l => l.id === group.id)
          if (!lane) return null
          const label =
            lane.id === 'battery'
              ? '+ chg'
              : lane.id === 'water'
              ? '+ wtr'
              : lane.id === 'export'
              ? '+ exp'
              : '+ hld'
          return (
            <div className="flex h-full items-center justify-center">
              <button
                type="button"
                className="flex h-12 w-12 items-center justify-center rounded-2xl border border-line/60 text-[11px] font-semibold hover:brightness-110"
                onClick={() => onAddBlock && onAddBlock(lane.id)}
                title={`Add ${lane.label.toLowerCase()} action`}
                style={{ backgroundColor: lane.color, color: '#0f1216' }}
              >
                {label}
              </button>
            </div>
          )
        }}
        onTimeChange={(start, end, updateScrollCanvas) => {
          const baseStartMs = baseStart.getTime()
          const baseEndMs = baseEnd.getTime()
          const requestedSpan = end - start
          const baseSpan = baseEndMs - baseStartMs

          // Ensure span does not exceed 48h window
          let newStart = start
          let newEnd = end

          if (requestedSpan > baseSpan) {
            newStart = baseStartMs
            newEnd = baseEndMs
          }

          // Clamp within [baseStart, baseEnd]
          if (newStart < baseStartMs) {
            const shift = baseStartMs - newStart
            newStart = baseStartMs
            newEnd += shift
          }
          if (newEnd > baseEndMs) {
            const shift = newEnd - baseEndMs
            newEnd = baseEndMs
            newStart -= shift
          }

          setVisibleStart(newStart)
          setVisibleEnd(newEnd)
          updateScrollCanvas(newStart, newEnd)
        }}
        onItemMove={(itemId: number | string, dragTime: number, newGroupOrder: number) => {
          const id = String(itemId)
          const original = blocks.find(b => b.id === id)
          if (!original || original.isHistorical) return
          if (!onBlockMove) return
          const start = new Date(dragTime)
          const lane = groups[newGroupOrder]?.id as LaneId
          onBlockMove({ id, start, lane })
        }}
        onItemResize={(itemId: number | string, time: number, edge: 'left' | 'right') => {
          const id = String(itemId)
          const movedTime = new Date(time)
          const original = blocks.find(b => b.id === id)
          if (!original || original.isHistorical) return
          if (!onBlockResize) return
          let start = original.start
          let end = original.end
          if (edge === 'left') {
            start = movedTime
          } else {
            end = movedTime
          }
          onBlockResize({ id, start, end })
        }}
        onItemSelect={(itemId: number | string) => {
          if (!onBlockSelect) return
          onBlockSelect(String(itemId))
        }}
          onItemDeselect={() => {
            if (!onBlockSelect) return
            onBlockSelect(null)
          }}
        />
      </div>
    </div>
  )
}
