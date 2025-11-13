import { useState } from 'react'
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
}

type PlanningTimelineProps = {
  lanes: PlanningLane[]
  blocks: PlanningBlock[]
  onBlockMove?: (args: { id: string; start: Date; lane: LaneId }) => void
  onBlockResize?: (args: { id: string; start: Date; end: Date }) => void
  onBlockSelect?: (id: string | null) => void
}

export default function PlanningTimeline({
  lanes,
  blocks,
  onBlockMove,
  onBlockResize,
  onBlockSelect,
}: PlanningTimelineProps) {
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
    className: `ds-timeline-item ds-timeline-${b.lane}`,
  }))

  const now = new Date()
  const baseStart = new Date(now)
  baseStart.setHours(0, 0, 0, 0)
  const baseEnd = new Date(baseStart.getTime() + 48 * 60 * 60 * 1000)

  const [visibleStart, setVisibleStart] = useState(baseStart.getTime())
  const [visibleEnd, setVisibleEnd] = useState(baseEnd.getTime())

  return (
    <div className="relative">
      <Timeline
        groups={groups}
        items={items}
        visibleTimeStart={visibleStart}
        visibleTimeEnd={visibleEnd}
        defaultTimeStart={baseStart}
        defaultTimeEnd={baseEnd}
        lineHeight={64}
        sidebarWidth={120}
        canMove
        canResize="both"
        canChangeGroup
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
          if (!onBlockMove) return
          const id = String(itemId)
          const start = new Date(dragTime)
          const lane = groups[newGroupOrder]?.id as LaneId
          onBlockMove({ id, start, lane })
        }}
        onItemResize={(itemId: number | string, time: number, edge: 'left' | 'right') => {
          if (!onBlockResize) return
          const id = String(itemId)
          const movedTime = new Date(time)
          const original = blocks.find(b => b.id === id)
          if (!original) return
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
  )
}
