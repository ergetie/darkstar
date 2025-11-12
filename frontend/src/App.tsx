import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Planning from './pages/Planning'
import Learning from './pages/Learning'
import Debug from './pages/Debug'
import Settings from './pages/Settings'

export default function App(){
    return (
        <BrowserRouter>
        <Sidebar />
        <div className="pl-[96px]">
        <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/planning" element={<Planning />} />
        <Route path="/learning" element={<Learning />} />
        <Route path="/debug" element={<Debug />} />
        <Route path="/settings" element={<Settings />} />
        </Routes>
        </div>
        </BrowserRouter>
    )
}
