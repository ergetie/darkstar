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
}

export default function PlanningTimeline({ lanes, blocks, onBlockMove, onBlockResize }: PlanningTimelineProps) {
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
  const start = new Date(now)
  start.setHours(0, 0, 0, 0)
  const end = new Date(start.getTime() + 48 * 60 * 60 * 1000)

  return (
    <div className="relative">
      <Timeline
        groups={groups}
        items={items}
        defaultTimeStart={start}
        defaultTimeEnd={end}
        lineHeight={64}
        sidebarWidth={120}
        canMove
        canResize="both"
        canChangeGroup
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
      />
    </div>
  )
}
