import { io, Socket } from 'socket.io-client'

// Singleton socket instance
let socket: Socket | null = null

export const getSocket = () => {
    if (!socket) {
        // REV F11: Fix Socket.IO connection for HA Ingress
        // document.baseURI respects <base href> tag injected by backend
        //
        // CRITICAL: Socket.IO's `path` option is appended to the ORIGIN, not the full URL.
        // The path MUST end with a trailing slash per Socket.IO requirements.
        const baseUrl = new URL(document.baseURI)

        // Ensure pathname ends with / before adding socket.io
        const basePath = baseUrl.pathname.endsWith('/') ? baseUrl.pathname : baseUrl.pathname + '/'

        // Socket.IO path must end with trailing slash
        const socketPath = basePath + 'socket.io/'

        console.log('🔌 Socket.IO Debug:', {
            baseURI: document.baseURI,
            origin: baseUrl.origin,
            pathname: baseUrl.pathname,
            socketPath: socketPath,
            fullUrl: baseUrl.origin + socketPath,
        })

        socket = io(baseUrl.origin, {
            path: socketPath,
            transports: ['polling', 'websocket'],
            autoConnect: true,
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
        })

        // Debug all socket events
        socket.onAny((event, ...args) => {
            console.log('🔌 Socket.IO event:', event, args)
        })

        socket.io.on('error', (error) => {
            console.error('🔌 Socket.IO Manager error:', error)
        })

        socket.io.on('ping', () => {
            console.log('🔌 Socket.IO ping')
        })

        socket.on('connect', () => {
            console.log('🔌 Connected to Darkstar WebSocket, id:', socket?.id)
        })

        socket.on('disconnect', (reason) => {
            console.warn('🔌 Disconnected from Darkstar WebSocket:', reason)
        })

        socket.on('connect_error', (error) => {
            console.error('🔌 WebSocket connection error:', error.message)
            console.error('🔌 Error details:', {
                name: error.name,
                message: error.message,
                // @ts-expect-error Socket.IO error may have description property
                description: error.description,
                // @ts-expect-error Socket.IO error may have context property
                context: error.context,
            })
        })
    }
    return socket
}
