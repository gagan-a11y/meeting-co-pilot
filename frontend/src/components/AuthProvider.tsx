'use client';

import { SessionProvider } from 'next-auth/react';
import { ReactNode } from 'react';

interface AuthProviderProps {
    children: ReactNode;
}

/**
 * Auth Provider Component
 * Wraps the app with NextAuth SessionProvider
 */
export function AuthProvider({ children }: AuthProviderProps) {
    return (
        <SessionProvider refetchInterval={5 * 60}>
            {children}
        </SessionProvider>
    );
}
