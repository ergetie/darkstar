#!/usr/bin/env python3
"""Test the new SoC colors in chart configuration."""

import json
import requests

# Test if the webapp is serving the updated JS with new colors
try:
    # Get the main page which includes the app.js
    response = requests.get('http://localhost:5000/', timeout=5)
    if response.status_code == 200:
        content = response.text
        
        # Check for the new color definitions
        if 'currentSoc: \'#FF1493\'' in content:
            print("✅ Current SoC color (deep pink) found in chart config")
        else:
            print("❌ Current SoC color not found")
            
        if 'historicSoc: \'#FF69B4\'' in content:
            print("✅ Historic SoC color (hot pink) found in chart config")
        else:
            print("❌ Historic SoC color not found")
            
        # Check if the colors are used in the datasets
        if 'colours.currentSoc' in content:
            print("✅ Current SoC color is used in datasets")
        else:
            print("❌ Current SoC color not used")
            
        if 'colours.historicSoc' in content:
            print("✅ Historic SoC color is used in datasets")
        else:
            print("❌ Historic SoC color not used")
            
    else:
        print(f"❌ Failed to get main page: {response.status_code}")
        
except Exception as e:
    print(f"❌ Error testing colors: {e}")