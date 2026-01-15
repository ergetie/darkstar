import { io, Socket } from 'socket.io-client'

// Singleton socket instance
let socket: Socket | null = null

export const getSocket = () => {
    if (!socket) {
        // REV F11: Fix Socket.IO connection for HA Ingress
        // Use document.baseURI which respects <base href> tag injected by backend
        // We must pass the FULL URL (origin + ingress path) to io() so that
        // Socket.IO connects to the correct proxied endpoint, not just window.location.origin
        const baseUrl = new URL(document.baseURI)
        // Remove trailing slash to avoid double-slash issues with socket.io path
        const socketUrl = baseUrl.origin + baseUrl.pathname.replace(/\/$/, '')

        console.log(`🔌 WebSocket initializing at URL: ${socketUrl}`)

        socket = io(socketUrl, {
            path: '/socket.io/', // Standard path, relative to socketUrl
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
