import { cls } from '../theme'
import { Rocket, CloudDownload, Upload, RotateCcw } from 'lucide-react'

export default function QuickActions(){
    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <button className={cls.accentBtn}><Rocket className="inline -mt-0.5 mr-2 h-4 w-4" />Run planner</button>
        <button className={cls.ghostBtn}><CloudDownload className="inline -mt-0.5 mr-2 h-4 w-4" />Load server plan</button>
        <button className={cls.ghostBtn}><Upload className="inline -mt-0.5 mr-2 h-4 w-4" />Push to DB</button>
        <button className={cls.ghostBtn}><RotateCcw className="inline -mt-0.5 mr-2 h-4 w-4" />Reset to optimal</button>
        </div>
    )
}
