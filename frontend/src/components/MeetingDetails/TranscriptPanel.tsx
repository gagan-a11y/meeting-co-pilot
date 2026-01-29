"use client";

import { Transcript } from '@/types';
import { TranscriptView } from '@/components/TranscriptView';
import { TranscriptButtonGroup } from './TranscriptButtonGroup';
import { TranscriptVersionSelector } from './TranscriptVersionSelector';
import { useState } from 'react';
import { toast } from 'sonner';
import { authFetch } from '@/lib/api';

interface TranscriptPanelProps {
  transcripts: Transcript[];
  onCopyTranscript: () => void;
  onOpenMeetingFolder: () => Promise<void>;
  isRecording: boolean;
  onDiarize?: () => void;
  diarizationStatus?: string;
  isDiarizing?: boolean;
  speakerMap?: { [label: string]: string };
  meetingId?: string; // Add meetingId
  onTranscriptsUpdate?: (transcripts: Transcript[]) => void; // Add update handler
}

export function TranscriptPanel({
  transcripts,
  onCopyTranscript,
  onOpenMeetingFolder,
  isRecording,
  onDiarize,
  diarizationStatus,
  isDiarizing,
  speakerMap,
  meetingId,
  onTranscriptsUpdate
}: TranscriptPanelProps) {
  const [currentVersion, setCurrentVersion] = useState<number | undefined>(undefined);

  const handleVersionChange = async (versionNum: number) => {
    if (!meetingId || !onTranscriptsUpdate) return;

    try {
      const response = await authFetch(`/meetings/${meetingId}/versions/${versionNum}`);
      if (!response.ok) throw new Error('Failed to fetch version');
      
      const data = await response.json();
      if (data.content) {
        // Map backend content to Transcript type if necessary, or assume it matches
        onTranscriptsUpdate(data.content);
        setCurrentVersion(versionNum);
        toast.success(`Switched to version ${versionNum}`);
      }
    } catch (error) {
      console.error('Error switching version:', error);
      toast.error('Failed to load transcript version');
    }
  };

  return (
    <div className="hidden md:flex md:w-1/4 lg:w-1/3 min-w-0 border-r border-gray-200 bg-white flex-col relative shrink-0">
      {/* Title area */}
      <div className="p-4 border-b border-gray-200">
        {meetingId && onTranscriptsUpdate && (
          <TranscriptVersionSelector 
            meetingId={meetingId} 
            onVersionChange={handleVersionChange}
            currentVersionNum={currentVersion}
            refreshTrigger={diarizationStatus} // Pass status as trigger
          />
        )}
        <TranscriptButtonGroup
          transcriptCount={transcripts?.length || 0}
          onCopyTranscript={onCopyTranscript}
          onOpenMeetingFolder={onOpenMeetingFolder}
          onDiarize={onDiarize}
          diarizationStatus={diarizationStatus}
          isDiarizing={isDiarizing}
        />
      </div>

      {/* Transcript content */}
      <div className="flex-1 overflow-y-auto pb-4">
        <TranscriptView 
          transcripts={transcripts} 
          speakerMap={speakerMap} 
          isRecording={isRecording}
          forceShowSpeakers={diarizationStatus === 'completed' || currentVersion !== undefined}
        />
      </div>
    </div>
  );
}
