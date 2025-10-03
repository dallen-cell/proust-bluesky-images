#!/usr/bin/env python3
"""
Bluesky Post Script
A simple script to post messages to Bluesky using the AT Protocol
"""

import os
from atproto import Client

def post_to_bluesky():
    """Post a message to Bluesky"""
    
    # Get credentials from environment variables
    username = os.environ.get('BLUESKY_USERNAME')
    password = os.environ.get('BLUESKY_APP_PASSWORD')
    
    if not username or not password:
        print("Error: BLUESKY_USERNAME and BLUESKY_APP_PASSWORD environment variables are required")
        print("\nPlease set your Bluesky credentials:")
        print("- BLUESKY_USERNAME: Your Bluesky handle (e.g., yourname.bsky.social)")
        print("- BLUESKY_APP_PASSWORD: Your app password (generate one at https://bsky.app/settings/app-passwords)")
        return
    
    # Define your static test message here
    message = "Hello from my Python automation script! 🤖"
    
    try:
        # Create client and login
        client = Client()
        print(f"Logging in as {username}...")
        client.login(username, password)
        
        # Post the message
        print(f"Posting message: '{message}'")
        response = client.send_post(text=message)
        
        print("✓ Successfully posted to Bluesky!")
        print(f"Post URI: {response.uri}")
        
    except Exception as e:
        print(f"✗ Error posting to Bluesky: {e}")

if __name__ == "__main__":
    post_to_bluesky()
