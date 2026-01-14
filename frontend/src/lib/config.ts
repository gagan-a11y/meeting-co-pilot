/**
 * Centralized Configuration for Meeting Co-Pilot
 * 
 * Automatically switches between development and production URLs
 * based on NODE_ENV environment variable.
 * 
 * Development (npm run dev): Uses localhost
 * Production (npm run build / Vercel): Uses env vars
 */

const isDevelopment = process.env.NODE_ENV === 'development';

export const config = {
  // HTTP API base URL
  apiUrl: isDevelopment 
    ? 'http://localhost:5167'
    : (process.env.NEXT_PUBLIC_BACKEND_URL || 'https://inflexibly-quakier-natashia.ngrok-free.dev'),
  
  // WebSocket URL for real-time streaming
  wsUrl: isDevelopment
    ? 'ws://localhost:5167/ws/streaming-audio'
    : (process.env.NEXT_PUBLIC_WS_URL || 'wss://inflexibly-quakier-natashia.ngrok-free.dev/ws/streaming-audio'),
  
  // Debug mode - enables extra logging
  debug: isDevelopment,
  
  // Environment name for logging
  environment: isDevelopment ? 'development' : 'production',
};

// Headers to skip ngrok browser warning (required for free tier)
export const ngrokHeaders = {
  'ngrok-skip-browser-warning': 'true',
};

// Helper function for fetch with ngrok headers
export async function fetchWithHeaders(url: string, options: RequestInit = {}): Promise<Response> {
  const headers = {
    ...ngrokHeaders,
    ...options.headers,
  };
  return fetch(url, { ...options, headers });
}

// Log configuration on startup (client-side only)
if (typeof window !== 'undefined' && config.debug) {
  console.log('[Config] Environment:', config.environment);
  console.log('[Config] API URL:', config.apiUrl);
  console.log('[Config] WS URL:', config.wsUrl);
}

// Export individual values for convenience
export const { apiUrl, wsUrl, debug } = config;
