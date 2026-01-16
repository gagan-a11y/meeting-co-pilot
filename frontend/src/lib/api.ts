import { getSession, signOut } from 'next-auth/react';
import { apiUrl } from './config';

/**
 * Authenticated Fetch Wrapper
 * Automatically adds Authorization header with JWT token
 * Handles session expiration by forcing logout
 */
export async function authFetch(endpoint: string, options: RequestInit = {}) {
  const session = await getSession();
  
  if (!session?.idToken) {
    console.warn('[AuthFetch] No active session found');
    throw new Error('Unauthorized: No active session');
  }

  // Handle refresh error - if token rotation failed, force sign out
  if ((session as any).error === "RefreshAccessTokenError") {
    console.error('[AuthFetch] Token refresh failed, forcing logout');
    signOut({ callbackUrl: '/login' });
    throw new Error('Session expired: Please log in again');
  }

  // Ensure endpoint starts with / if not absolute
  const url = endpoint.startsWith('http') 
    ? endpoint 
    : `${apiUrl}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;

  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${session.idToken}`,
    ...options.headers,
  };

  const response = await fetch(url, {
    ...options,
    headers,
  });

  // Handle 401 Unauthorized from backend
  if (response.status === 401) {
    console.warn('[AuthFetch] Backend returned 401 Unauthorized - Token may be expired or invalid');
    
    // Check if we can refresh the session
    const updatedSession = await getSession();
    
    // If the token was refreshed, updatedSession.idToken will be different
    if (updatedSession?.idToken && updatedSession.idToken !== session.idToken) {
      console.log('[AuthFetch] Token was refreshed during 401, retrying request...');
      const newHeaders = {
        ...headers,
        'Authorization': `Bearer ${updatedSession.idToken}`,
      };
      return fetch(url, {
        ...options,
        headers: newHeaders,
      });
    }

    // If refresh failed or wasn't triggered, force logout
    console.error('[AuthFetch] Session invalid, forcing logout');
    signOut({ callbackUrl: '/login' });
    throw new Error('Session expired: Please log in again');
  }

  return response;
}

/**
 * Hook-friendly helpers can be added here if needed
 */
