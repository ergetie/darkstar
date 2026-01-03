#!/usr/bin/env python3
import requests
import sys
import json

def verify_secrets():
    print("Locked & Loaded: Checking for leaked secrets in /api/config...")
    try:
        r = requests.get("http://localhost:5000/api/config", timeout=2)
        r.raise_for_status()
        data = r.json()
        
        leaked = []
        
        # Check HA token
        if "home_assistant" in data:
            if "token" in data["home_assistant"]:
                leaked.append("home_assistant.token")
                
        # Check Notifications
        if "notifications" in data:
            for field in ["api_key", "token", "password", "webhook_url"]:
                if field in data["notifications"]:
                    leaked.append(f"notifications.{field}")
                    
        if leaked:
            print(f"❌ SECURITY FAIL: Found leaked secrets: {', '.join(leaked)}")
            sys.exit(1)
            
        print("✅ SECURITY PASS: No leaked secrets found.")
        sys.exit(0)
        
    except Exception as e:
        print(f"❌ Error connecting to API: {e}")
        sys.exit(1)

if __name__ == "__main__":
    verify_secrets()
