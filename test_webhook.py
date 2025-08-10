#!/usr/bin/env python3
"""
Simple test script to verify webhook setup works
"""

import requests
import json

def test_endpoints():
    """Test all Flask endpoints"""
    base_url = "https://timer-quiz-y7gc.onrender.com"
    
    endpoints = [
        ("/", "Home endpoint"),
        ("/health", "Health check"),
        ("/stats", "Bot stats"),
        ("/setup_webhook", "Webhook setup")
    ]
    
    print("🧪 Testing endpoints...\n")
    
    for endpoint, description in endpoints:
        try:
            url = f"{base_url}{endpoint}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                print(f"✅ {description}: {endpoint} - OK")
                if endpoint == "/setup_webhook":
                    data = response.json()
                    print(f"   Webhook setup result: {data.get('message', 'Success')}")
            else:
                print(f"❌ {description}: {endpoint} - Status {response.status_code}")
                
        except Exception as e:
            print(f"❌ {description}: {endpoint} - Error: {e}")
    
    print("\n🔧 To set up your webhook after deployment, visit:")
    print(f"   {base_url}/setup_webhook")

if __name__ == "__main__":
    test_endpoints()
