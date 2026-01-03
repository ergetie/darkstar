#!/usr/bin/env python3
import asyncio
import socketio
import sys

# Create async socket client
sio = socketio.AsyncClient()
received_event = asyncio.Event()

@sio.event
async def connect():
    print("✅ WebSocket Connected")

@sio.event
async def connect_error(data):
    print(f"❌ WebSocket Connect Error: {data}")

@sio.event
async def live_metrics(data):
    print(f"⚡ live_metrics received: {data}")
    if data and ('load_kw' in data or 'pv_kw' in data):
        print("🎉 Validation Successful: Live power data flowing!")
        received_event.set()
    else:
        print("⚠️ Received empty/invalid metrics")

async def main():
    print("🔍 Starting WebSocket Verification...")
    try:
        await sio.connect('http://localhost:5000')
        
        # Wait for event with timeout
        try:
            await asyncio.wait_for(received_event.wait(), timeout=10.0)
            print("✅ WebSocket verification passed.")
            await sio.disconnect()
            sys.exit(0)
        except asyncio.TimeoutError:
            print("❌ WebSocket Validation Timed Out (No live_metrics received)")
            await sio.disconnect()
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ WebSocket Client Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
