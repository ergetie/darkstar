import { Manager, Socket } from 'socket.io-client'

// Singleton socket instance
let socket: Socket | null = null

export const getSocket = () => {
    if (!socket) {
        // REV F11: Fix Socket.IO connection for HA Ingress
        // document.baseURI respects <base href> tag injected by backend

        const baseUrl = new URL(document.baseURI)
        const isIngressPath = baseUrl.pathname.includes('hassio_ingress')

        // Ensure pathname ends with / before adding socket.io
        const basePath = baseUrl.pathname.endsWith('/') ? baseUrl.pathname : baseUrl.pathname + '/'

        // For Ingress: try full path first, HA may or may not strip it
        const socketPath = basePath + 'socket.io/'

        console.log('========================================')
        console.log('🔌 Socket.IO Connection Diagnosis (Manager Pattern)')
        console.log('========================================')
        console.log('📍 document.baseURI:', document.baseURI)
        console.log('📍 Origin:', baseUrl.origin)
        console.log('📍 Pathname:', baseUrl.pathname)
        console.log('📍 Is Ingress:', isIngressPath)
        console.log('📍 Socket Path:', socketPath)
        console.log('========================================')

        // 1. Create the Manager: Handles the low-level connection (Engine.IO)
        // We configure the path here to ensure it travels through HA Ingress correctly.
        // REV F11 UPDATE: Runtime configuration for debugging without redeploy

        const params = new URLSearchParams(window.location.search)
        const overridePath = params.get('socket_path')
        const overrideTransports = params.get('socket_transports')?.split(',')

        // Default: Force websocket, remove trailing slash
        const finalPath = overridePath || socketPath.replace(/\/$/, '')
        const finalTransports = overrideTransports || ['websocket']

        console.log('🔧 Socket Config Overrides:', {
            overridePath,
            overrideTransports,
            finalPath,
            finalTransports,
        })

        const manager = new Manager(baseUrl.origin, {
            path: finalPath,
            transports: finalTransports,
            autoConnect: false, // We will connect manually
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            reconnectionAttempts: 10,
        })

        // 2. Create the Socket: Handles the application protocol (Namespace)
        // We EXPLICITLY connect to the default namespace '/' to avoid any auto-discovery ambiguity.
        socket = manager.socket('/')

        // Debug Manager events (Transport Layer)
        manager.on('open', () => {
            console.log('🔌 Manager: Transport OPENED')
            // Log the transport details
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const transport = (manager.engine as any).transport
            console.log('   Transport Type:', transport.name)
            console.log('   Transport URL:', transport.opts.path)

            // Hook into low-level packet creation to see what we are sending
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            manager.engine.on('packetCreate', (packet: any) => {
                console.log('📤 Manager: Sending Packet:', packet.type, packet.data)
            })

            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            manager.engine.on('packet', (packet: any) => {
                console.log('📥 Manager: Received Packet:', packet.type, packet.data)
            })
        })

        manager.on('error', (err: Error) => console.error('🔌 Manager: Transport ERROR:', err))
        manager.on('close', (reason: string) => console.log('🔌 Manager: Transport CLOSED:', reason))
        manager.on('reconnect_attempt', (attempt: number) => console.log(`🔌 Manager: Reconnect attempt ${attempt}`))

        // Manually trigger connection now that listeners are attached
        console.log('🔌 Manager: Initiating manual connection...')
        manager.open((err?: Error) => {
            if (err) {
                console.error('🔌 Manager: Open failed:', err)
            } else {
                console.log('🔌 Manager: Open successful, connecting socket...')
                socket?.connect()
            }
        })

        // Debug Socket events (Application Layer)
        socket.onAny((event, ...args) => {
            console.log('🔌 Socket.IO RX event:', event, args)
        })

        socket.on('connect', () => {
            console.log('✅ Socket.IO CONNECTED! SID:', socket?.id)
        })

        socket.on('disconnect', (reason: string) => {
            console.warn('🔌 Socket.IO DISCONNECTED:', reason)
        })

        socket.on('connect_error', (error: Error) => {
            console.error('❌ Socket.IO connect_error:', error.message)
            // Hint for debugging
            if (error.message.includes('xhr poll error')) {
                console.error('💡 HINT: XHR poll error usually means:')
                console.error('   1. Wrong path - server not listening at:', socketPath)
                console.error('   2. CORS issue')
                console.error('   3. Proxy issue - HA Ingress not forwarding correctly')
            }
        })
    }
    return socket
}
