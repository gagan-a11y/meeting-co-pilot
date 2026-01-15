# User-Provided API Keys (Personal Keys)

## Overview
This feature allows individual users to provide their own API keys (e.g., Grok/xAI, Gemini, OpenAI) to power their sessions, rather than relying solely on the system-wide API keys. This improves security, allows for personal usage tracking, and enables users to use their own specialized models.

## Problem
Currently, all API calls use keys defined in the server's `.env` file. This means the system owner bears all costs and users cannot benefit from their own higher-tier API access or usage limits.

## Proposed Solution
Implement a "Personal API Keys" section in the user settings. These keys will be stored securely and prioritized over system keys when that specific user is performing actions.

### Key Capabilities
- **Grok/xAI Integration**: Specific support for Grok API keys as requested.
- **Secure Backend Storage**: Keys are encrypted at rest and never returned to the frontend after initial setup (except as masked strings like `gsk_...xxxx`).
- **Provider Priority Logic**: System follows a simple hierarchy: `User Key` -> `Workspace Key` (Future) -> `System Key`.
- **Validation**: Test the key immediately upon entry to ensure it works.

## Technical Architecture

### Database Changes
- **New Table**: `user_api_keys`
    - `user_email` (Foreign Key to users)
    - `provider` (e.g., 'grok', 'gemini', 'openai')
    - `api_key` (Encrypted string)
    - `is_active` (Boolean)
    - `created_at` / `updated_at`

### Backend
- **Encryption Service**: A utility to encrypt/decrypt strings using a system-level master key.
- **Key Discovery Utility**: A function `get_effective_api_key(user_email, provider)` that handles the fallback logic.
- **Secure Endpoints**:
    - `POST /settings/api-keys`: Save/Update a key.
    - `GET /settings/api-keys`: List active providers (not the keys themselves).
    - `DELETE /settings/api-keys/{provider}`: Remove a key.

### Frontend
- **Settings UI**: A new tab or section in the Settings page for "Personal API Keys."
- **Masked Inputs**: Standard security UI for entering sensitive keys.
- **Provider Status**: Visual indicator showing if a personal key is being used or if it's falling back to system defaults.

## Security Considerations
- **Encryption at Rest**: Mandatory for all user-provided keys.
- **In-Memory Security**: Decrypted keys should never be logged or exposed in error messages.
- **Domain Restriction**: Keys should only be usable by the user who provided them.

## Implementation Phases
1. **Phase 1: Encryption & DB Schema**: Set up the secure storage layer.
2. **Phase 2: Grok Key Integration**: Implement saving and retrieving Grok-specific keys first.
3. **Phase 3: Multi-Provider Support**: Expand to Gemini, OpenAI, and other configured providers.
4. **Phase 4: Consumption Tracking**: (Future) Show users how much of their own quota they've used.
