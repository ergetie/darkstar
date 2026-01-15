import { io, Socket } from 'socket.io-client'

// Singleton socket instance
let socket: Socket | null = null

export const getSocket = () => {
    if (!socket) {
        // REV F11: Fix Socket.IO connection for HA Ingress
        // document.baseURI respects <base href> tag injected by backend
        //
        // CRITICAL: Socket.IO's `path` option is appended to the ORIGIN, not the full URL.
        // So we must:
        //   1. Connect to the origin (https://home.wxl.se)
        //   2. Set path to include the ingress prefix (/api/hassio_ingress/xxx/socket.io)
        //
        // This ensures requests go to: origin + path = correct proxied endpoint
        const baseUrl = new URL(document.baseURI)

        // Build socket.io path: ingress pathname + /socket.io
        // e.g., /api/hassio_ingress/xxx/ -> /api/hassio_ingress/xxx/socket.io
        const socketPath = (baseUrl.pathname + 'socket.io').replace(/\/\//g, '/')

        console.log(`🔌 WebSocket initializing: origin=${baseUrl.origin}, path=${socketPath}`)

        socket = io(baseUrl.origin, {
            path: socketPath, // Full path including ingress prefix
            transports: ['polling', 'websocket'],
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
