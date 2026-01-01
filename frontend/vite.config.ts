import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
    plugins: [react()],
    server: {
        host: '0.0.0.0', // Allow access from LAN (e.g., 192.168.x.x)
        port: 5173,
        proxy: {
            '/api': {
                target: 'http://127.0.0.1:5000',
                changeOrigin: true,
                secure: false,
            },
        },
    },
    build: {
        outDir: '../backend/static',
        emptyOutDir: true,
        // Use relative paths for HA Add-on Ingress compatibility
        assetsDir: 'assets',
    },
    // Relative base path for HA Ingress (serves from subpath)
    base: './',
})
