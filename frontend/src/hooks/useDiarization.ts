
import { useState, useEffect, useCallback } from 'react';
import { authFetch } from '@/lib/api';

export interface DiarizationStatus {
  meeting_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'not_recorded' | 'stopped';
  speaker_count?: number;
  provider?: string;
  error?: string;
  completed_at?: string;
}

export interface SpeakerMapping {
  label: string;
  display_name: string;
  color?: string;
}

export function useDiarization(meetingId: string) {
  const [status, setStatus] = useState<DiarizationStatus | null>(null);
  const [speakers, setSpeakers] = useState<SpeakerMapping[]>([]);
  const [isDiarizing, setIsDiarizing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    if (!meetingId) return;
    try {
      const response = await authFetch(`/meetings/${meetingId}/diarization-status`);
      if (response.ok) {
        const data = await response.json();
        setStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch diarization status:', err);
    }
  }, [meetingId]);

  const fetchSpeakers = useCallback(async () => {
    if (!meetingId) return;
    try {
      const response = await authFetch(`/meetings/${meetingId}/speakers`);
      if (response.ok) {
        const data = await response.json();
        setSpeakers(data.speakers || []);
      }
    } catch (err) {
      console.error('Failed to fetch speakers:', err);
    }
  }, [meetingId]);

  // Initial load
  useEffect(() => {
    fetchStatus();
    fetchSpeakers();
  }, [meetingId, fetchStatus, fetchSpeakers]);

  // Separate polling effect
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (status?.status === 'processing') {
       interval = setInterval(fetchStatus, 5000);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [status?.status, fetchStatus]);

  const triggerDiarization = async () => {
    setIsDiarizing(true);
    setError(null);
    try {
      const response = await authFetch(`/meetings/${meetingId}/diarize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'deepgram' }) // Default to deepgram
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Diarization failed');
      }

      await fetchStatus();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsDiarizing(false);
    }
  };

  const stopDiarization = async () => {
    try {
      const response = await authFetch(`/meetings/${meetingId}/diarize/stop`, {
        method: 'POST',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to stop diarization');
      }

      await fetchStatus();
    } catch (err: any) {
      console.error('Failed to stop diarization:', err);
      setError(err.message);
    }
  };

  const renameSpeaker = async (label: string, newName: string) => {
    try {
      const response = await authFetch(`/meetings/${meetingId}/speakers/${label}/rename`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: newName })
      });

      if (!response.ok) {
        throw new Error('Failed to rename speaker');
      }

      // Optimistic update
      setSpeakers(prev => prev.map(s => 
        s.label === label ? { ...s, display_name: newName } : s
      ));
      
      return true;
    } catch (err) {
      console.error(err);
      return false;
    }
  };

  return {
    status,
    speakers,
    isDiarizing,
    error,
    triggerDiarization,
    stopDiarization,
    renameSpeaker,
    refreshSpeakers: fetchSpeakers
  };
}
