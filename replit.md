# Overview

This is a simple Python automation script that posts messages to Bluesky (a decentralized social network) using the AT Protocol. The script authenticates with Bluesky credentials and sends a predefined text message to the user's feed.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Application Structure
- **Single-file Python script**: The entire application is contained in `main.py`, following a simple procedural approach suitable for automation tasks
- **Environment-based configuration**: Credentials are stored in environment variables (`BLUESKY_USERNAME` and `BLUESKY_APP_PASSWORD`) to keep sensitive data separate from code

## Authentication Flow
- **App password authentication**: Uses Bluesky's app password system (not the main account password) for secure API access
- **Session-based login**: Creates a client session, authenticates, and posts within the same execution context
- **Error handling**: Validates that required credentials exist before attempting authentication, providing helpful error messages if missing

## Core Functionality
- **Static message posting**: Currently configured to post a hardcoded message; designed to be easily modified for dynamic content
- **AT Protocol integration**: Uses the `atproto` Python library as the official client for interacting with Bluesky's API
- **Response tracking**: Captures and displays the post URI after successful submission for verification

## Design Decisions

**Problem**: Need to automate posting to Bluesky  
**Solution**: Single-file Python script with environment-based credentials  
**Rationale**: Simplicity and ease of modification; suitable for cron jobs, scheduled tasks, or integration into larger automation workflows

**Problem**: Secure credential management  
**Solution**: Environment variables for username and app password  
**Rationale**: Keeps credentials out of version control; follows security best practices; app passwords can be revoked without changing main account password

# External Dependencies

## Third-Party Libraries
- **atproto**: Official Python SDK for the AT Protocol (Bluesky's underlying protocol)
  - Purpose: Handles authentication and API communication with Bluesky
  - Key methods used: `Client()`, `login()`, `send_post()`

## External Services
- **Bluesky Social Network**: The target platform for posting
  - Authentication endpoint: Uses handle and app password
  - App password generation: Available at https://bsky.app/settings/app-passwords
  - API: AT Protocol (Authenticated Transfer Protocol)

## Environment Variables
- `BLUESKY_USERNAME`: User's Bluesky handle (e.g., username.bsky.social)
- `BLUESKY_APP_PASSWORD`: Application-specific password for API access