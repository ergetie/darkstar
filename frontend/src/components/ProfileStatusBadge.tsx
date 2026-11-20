import type { InverterProfile } from '../pages/settings/types'
import { Badge } from './ui/Banner'

interface ProfileStatusBadgeProps {
    /** Status reported by the backend; a missing value (older backend) counts as community. */
    status: InverterProfile['status']
}

/** "Tested" (hardware-verified) or "Community" badge for an inverter profile. */
export function ProfileStatusBadge({ status }: ProfileStatusBadgeProps) {
    return status === 'tested' ? <Badge variant="good">Tested</Badge> : <Badge variant="muted">Community</Badge>
}
