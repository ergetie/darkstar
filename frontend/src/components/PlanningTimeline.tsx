import Timeline from 'react-calendar-timeline'

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
}

export default function PlanningTimeline({ lanes, blocks }: PlanningTimelineProps) {
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
    className: 'bg-accent/60 border-none',
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
        lineHeight={48}
        sidebarWidth={120}
        canMove={false}
        canResize={false}
        canChangeGroup={false}
      />
    </div>
  )
}
