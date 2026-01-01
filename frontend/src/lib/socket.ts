import { io, Socket } from 'socket.io-client'

// Singleton socket instance
let socket: Socket | null = null

export const getSocket = () => {
    if (!socket) {
        // Dynamically calculate the correct path for HA Ingress compatibility (Rev U21)
        // If we're at /some/subpath/page, we want /some/subpath/socket.io
        let pathname = window.location.pathname
        if (!pathname.endsWith('/')) {
            pathname = pathname.substring(0, pathname.lastIndexOf('/') + 1)
        }
        const socketPath = (pathname + 'socket.io').replace(/\/\//g, '/')

        console.log(`🔌 WebSocket initializing at path: ${socketPath}`)

        socket = io({
            path: socketPath,
            transports: ['polling', 'websocket'], // Ensure fallback works
            autoConnect: true,
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
        })

        socket.on('connect', () => {
            console.log('🔌 Connected to Darkstar WebSocket')
        })

        socket.on('disconnect', (reason) => {
            console.warn('🔌 Disconnected from Darkstar WebSocket:', reason)
        })

        socket.on('connect_error', (error) => {
            console.error('🔌 WebSocket connection error:', error)
        })
    }
    return socket
}
