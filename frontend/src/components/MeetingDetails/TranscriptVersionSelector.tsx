'use client';

import { useState, useEffect } from 'react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { authFetch } from '@/lib/api';

interface TranscriptVersion {
  version_num: number;
  source: string;
  is_authoritative: boolean;
  created_at: string;
  confidence_metrics: {
    avg_confidence: number;
    confident_count: number;
    uncertain_count: number;
    overlap_count: number;
  };
}

interface TranscriptVersionSelectorProps {
  meetingId: string;
  onVersionChange: (versionNum: number) => void;
  currentVersionNum?: number;
  refreshTrigger?: any; // New prop to trigger re-fetch
}

export function TranscriptVersionSelector({
  meetingId,
  onVersionChange,
  currentVersionNum,
  refreshTrigger
}: TranscriptVersionSelectorProps) {
  const [versions, setVersions] = useState<TranscriptVersion[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchVersions();
  }, [meetingId, refreshTrigger]); // Add refreshTrigger to dependencies

  const fetchVersions = async () => {
    try {
      const response = await authFetch(`/meetings/${meetingId}/versions`);
      if (response.ok) {
        const data = await response.json();
        setVersions(data.versions);
      }
    } catch (error) {
      console.error('Failed to fetch transcript versions:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return null;

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm font-medium text-gray-700">Version:</span>
      <Select
        value={currentVersionNum?.toString()}
        onValueChange={(val) => onVersionChange(parseInt(val))}
      >
        <SelectTrigger className="w-[250px]">
          <SelectValue placeholder="Select version" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="-1">
            <div className="flex items-center justify-between w-full gap-2">
              <span>Live Transcript</span>
              <Badge variant="outline" className="ml-2 text-xs">Current</Badge>
            </div>
          </SelectItem>
          {versions.map((v) => (
            <SelectItem key={v.version_num} value={v.version_num.toString()}>
              <div className="flex items-center justify-between w-full gap-2">
                <span>v{v.version_num} ({v.source})</span>
                {v.is_authoritative && <Badge variant="secondary" className="ml-2 text-xs">Active</Badge>}
                {v.confidence_metrics && (
                  <span className="text-xs text-gray-400 ml-auto">
                    {Math.round(v.confidence_metrics.avg_confidence * 100)}% conf
                  </span>
                )}
              </div>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
