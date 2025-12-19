#!/usr/bin/env python
"""
Debug script to test Discord notification when HA is down.

This simulates what happens in run_planner error handler:
1. Loads config.yaml (local, should work)
2. Tries to send HA notification (should fail)
3. Falls back to Discord (should work)
"""
import sys
import os

sys.path.insert(0, os.getcwd())

# Test 1: Can we read the Discord webhook from config?
print("=" * 50)
print("TEST 1: Read Discord webhook from config.yaml")
print("=" * 50)

import yaml

try:
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f) or {}
    
    executor_cfg = config.get("executor", {})
    notif_cfg = executor_cfg.get("notifications", {})
    discord_webhook_url = notif_cfg.get("discord_webhook_url")
    ha_service = notif_cfg.get("service")
    
    print(f"✅ Config loaded successfully")
    print(f"   Discord webhook: {'SET' if discord_webhook_url else 'NOT SET'}")
    print(f"   HA service: {ha_service or 'NOT SET'}")
    
    if not discord_webhook_url:
        print("❌ PROBLEM: Discord webhook not configured!")
        print("   Path: executor.notifications.discord_webhook_url")
        sys.exit(1)
        
except Exception as e:
    print(f"❌ Failed to load config: {e}")
    sys.exit(1)

# Test 2: Try Discord notification directly
print("\n" + "=" * 50)
print("TEST 2: Send Discord notification directly")
print("=" * 50)

from backend.notify import send_critical_notification

# Don't try HA (no url/token), just test Discord
result = send_critical_notification(
    title="[TEST] Darkstar Notification Test",
    message="This is a test notification from debug/test_discord_notification.py. If you see this, Discord fallback works!",
    ha_service=None,  # Skip HA
    ha_url=None,
    ha_token=None,
    discord_webhook_url=discord_webhook_url,
)

if result:
    print("✅ Discord notification sent successfully!")
else:
    print("❌ Discord notification FAILED")

# Test 3: Simulate the full error handler flow
print("\n" + "=" * 50)
print("TEST 3: Simulate full error handler flow (HA fail → Discord)")
print("=" * 50)

from inputs import load_home_assistant_config

ha_config = load_home_assistant_config() or {}
print(f"   HA config loaded: {bool(ha_config)}")
print(f"   HA URL: {ha_config.get('url', 'NOT SET')[:30]}..." if ha_config.get('url') else "   HA URL: NOT SET")

# Now simulate what run_planner does
result = send_critical_notification(
    title="[TEST] Full Error Handler Flow",
    message="Testing HA-first → Discord fallback chain from debug script.",
    ha_service=ha_service,
    ha_url=ha_config.get("url"),
    ha_token=ha_config.get("token"),
    discord_webhook_url=discord_webhook_url,
)

if result:
    print("✅ Notification sent (via HA or Discord fallback)")
else:
    print("❌ ALL notification methods failed!")

print("\n" + "=" * 50)
print("DONE")
print("=" * 50)
