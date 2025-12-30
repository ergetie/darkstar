import { io, Socket } from "socket.io-client"

// Singleton socket instance
let socket: Socket | null = null

export const getSocket = () => {
    if (!socket) {
        // Use relative path for HA Ingress compatibility
        // The socket.io-client will use the current window.location by default
        socket = io({
            path: "/socket.io",
            autoConnect: true,
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
        })

        socket.on("connect", () => {
            console.log("🔌 Connected to Darkstar WebSocket")
        })

        socket.on("disconnect", (reason) => {
            console.warn("🔌 Disconnected from Darkstar WebSocket:", reason)
        })

        socket.on("connect_error", (error) => {
            console.error("🔌 WebSocket connection error:", error)
        })
    }
    return socket
}
