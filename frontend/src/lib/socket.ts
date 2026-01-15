import { io, Socket } from 'socket.io-client'

// Singleton socket instance
let socket: Socket | null = null
let connectionAttempts = 0

export const getSocket = () => {
    if (!socket) {
        // REV F11: Fix Socket.IO connection for HA Ingress
        // document.baseURI respects <base href> tag injected by backend
        //
        // DEBUG: We'll try two approaches:
        // 1. Full ingress path: /api/hassio_ingress/xxx/socket.io/
        // 2. Standard path: /socket.io/ (if HA Ingress strips prefix)

        const baseUrl = new URL(document.baseURI)
        const isIngressPath = baseUrl.pathname.includes('hassio_ingress')

        // Ensure pathname ends with / before adding socket.io
        const basePath = baseUrl.pathname.endsWith('/') ? baseUrl.pathname : baseUrl.pathname + '/'

        // For Ingress: try full path first, HA may or may not strip it
        const socketPath = basePath + 'socket.io/'

        console.log('========================================')
        console.log('🔌 Socket.IO Connection Diagnosis')
        console.log('========================================')
        console.log('📍 document.baseURI:', document.baseURI)
        console.log('📍 Origin:', baseUrl.origin)
        console.log('📍 Pathname:', baseUrl.pathname)
        console.log('📍 Is Ingress:', isIngressPath)
        console.log('📍 Socket Path:', socketPath)
        console.log('📍 Full URL will be:', baseUrl.origin + socketPath)
        console.log('========================================')

        socket = io(baseUrl.origin, {
            path: socketPath,
            transports: ['polling', 'websocket'],
            autoConnect: true,
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            reconnectionAttempts: 5, // Limit retries for debugging
        })

        // Debug all socket events
        socket.onAny((event, ...args) => {
            console.log('🔌 Socket.IO RX event:', event, args)
        })

        socket.io.on('error', (error) => {
            console.error('🔌 Socket.IO Transport error:', error)
        })

        socket.io.on('ping', () => {
            console.log('🔌 Socket.IO ping received')
        })

        socket.io.on('reconnect_attempt', (attempt) => {
            connectionAttempts = attempt
            console.log(`🔌 Socket.IO reconnect attempt ${attempt}`)
        })

        socket.io.on('open', () => {
            console.log('🔌 Socket.IO Transport OPENED (low-level connection established)')
        })

        socket.io.on('close', (reason) => {
            console.log('🔌 Socket.IO Transport CLOSED:', reason)
        })

        socket.on('connect', () => {
            console.log('✅ Socket.IO CONNECTED! SID:', socket?.id)
            console.log('   Transport:', socket?.io.engine?.transport?.name)
        })

        socket.on('disconnect', (reason) => {
            console.warn('🔌 Socket.IO DISCONNECTED:', reason)
        })

        socket.on('connect_error', (error) => {
            console.error('❌ Socket.IO connect_error:', error.message)
            console.error('   Full error:', error)
            // Log transport state
            console.error('   Transport ready state:', socket?.io.engine?.readyState)
            console.error('   Connection attempts:', connectionAttempts)

            // Hint for debugging
            if (error.message.includes('xhr poll error')) {
                console.error('💡 HINT: XHR poll error usually means:')
                console.error('   1. Wrong path - server not listening at:', socketPath)
                console.error('   2. CORS issue - check server CORS config')
                console.error('   3. Proxy issue - HA Ingress not forwarding correctly')
            }
        })
    }
    return socket
}
