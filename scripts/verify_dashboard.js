
import { io } from "socket.io-client";
import fetch from "node-fetch";

const BASE_URL = "http://localhost:5000";

async function verify() {
    console.log("🔍 Starting Verification...");

    // 1. API CHECKS
    try {
        const r = await fetch(`${BASE_URL}/api/status`);
        if (r.ok) {
            const data = await r.json();
            console.log(`✅ API Status: OK (Rev: ${data.rev})`);
            if (data.soc_percent !== undefined) console.log(`   SoC: ${data.soc_percent}%`);
        } else {
            console.error(`❌ API Status Failed: ${r.status}`);
            process.exit(1);
        }
    } catch (e) {
        console.error(`❌ API Connection Failed: ${e.message}`);
        process.exit(1);
    }

    // 2. WEBSOCKET CHECK
    console.log("🔌 Connecting to WebSocket...");
    const socket = io(BASE_URL, {
        transports: ["websocket", "polling"],
        reconnection: false,
        timeout: 5000
    });

    const timeout = setTimeout(() => {
        console.error("❌ WebSocket Validation Timed Out (No live_metrics received)");
        socket.disconnect();
        process.exit(1);
    }, 10000);

    socket.on("connect", () => {
        console.log("✅ WebSocket Connected");
    });

    socket.on("connect_error", (err) => {
        console.error(`❌ WebSocket Connect Error: ${err.message}`);
    });

    socket.on("live_metrics", (data) => {
        console.log("⚡ live_metrics received:", data);
        if (data && (data.load_kw !== undefined || data.pv_kw !== undefined)) {
            console.log("🎉 Validation Successful: Live power data flowing!");
            clearTimeout(timeout);
            socket.disconnect();
            process.exit(0);
        } else {
            console.log("⚠️ Received empty/invalid metrics");
        }
    });
}

verify();
