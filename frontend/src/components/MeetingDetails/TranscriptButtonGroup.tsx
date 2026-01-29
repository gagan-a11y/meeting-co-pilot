"use client";

import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Copy, FolderOpen, Users, Loader2 } from 'lucide-react';
import Analytics from '@/lib/analytics';


interface TranscriptButtonGroupProps {
  transcriptCount: number;
  onCopyTranscript: () => void;
  onOpenMeetingFolder: () => Promise<void>;
  onDiarize?: () => void;
  diarizationStatus?: string;
  isDiarizing?: boolean;
  isRecording?: boolean;
}


export function TranscriptButtonGroup({
  transcriptCount,
  onCopyTranscript,
  onOpenMeetingFolder,
  onDiarize,
  diarizationStatus,
  isDiarizing,
  isRecording
}: TranscriptButtonGroupProps) {
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex gap-2">
        {onDiarize && (
          <Button
            size="sm"
            variant={diarizationStatus === 'completed' ? "outline" : (diarizationStatus === 'processing' ? "secondary" : "default")}
            className={diarizationStatus === 'completed' ? "" : "bg-indigo-600 hover:bg-indigo-700 text-white"}
            onClick={onDiarize}
            disabled={isDiarizing || diarizationStatus === 'processing' || isRecording}
          >
            {isDiarizing || diarizationStatus === 'processing' ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Users className="mr-2 h-4 w-4" />
            )}
            <span className="hidden lg:inline">
              {diarizationStatus === 'processing' ? 'Identifying...' :
                (diarizationStatus === 'completed' ? 'Re-identify Speakers' : 
                 (diarizationStatus === 'failed' ? 'Failed (Retry)' : 'Identify Speakers'))}
            </span>
          </Button>
        )}
      </div>

      <ButtonGroup>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            Analytics.trackButtonClick('copy_transcript', 'meeting_details');
            onCopyTranscript();
          }}
          disabled={transcriptCount === 0}
          title={transcriptCount === 0 ? 'No transcript available' : 'Copy Transcript'}
        >
          <Copy className="h-4 w-4 lg:mr-2" />
          <span className="hidden lg:inline">Copy</span>
        </Button>

        <Button
          size="sm"
          variant="outline"
          className="xl:px-4"
          onClick={() => {
            Analytics.trackButtonClick('open_recording_folder', 'meeting_details');
            onOpenMeetingFolder();
          }}
          title="Open Recording Folder"
        >
          <FolderOpen className="h-4 w-4 lg:mr-2" />
          <span className="hidden lg:inline">Recording</span>
        </Button>
      </ButtonGroup>
    </div>
  );
}
