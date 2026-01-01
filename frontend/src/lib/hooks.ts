import { useEffect } from 'react'
import { getSocket } from './socket'

export const useSocket = (event: string, callback: (data: unknown) => void) => {
    useEffect(() => {
        const socket = getSocket()
        socket.on(event, callback)

        return () => {
            socket.off(event, callback)
        }
    }, [event, callback])
}
