import { io, Socket } from 'socket.io-client'

// Singleton socket instance
let socket: Socket | null = null

export const getSocket = () => {
    if (!socket) {
        // Use document.baseURI which respects <base href> tag for HA Ingress (Rev U21)
        // This ensures socket.io connects to the correct path when running under HA Ingress
        const baseUrl = new URL(document.baseURI)
        const socketPath = (baseUrl.pathname + 'socket.io').replace(/\/\//g, '/')

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
