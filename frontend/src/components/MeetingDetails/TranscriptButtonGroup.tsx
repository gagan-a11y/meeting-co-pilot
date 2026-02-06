"use client";

import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Copy, Download, Users, Loader2 } from 'lucide-react';
import Analytics from '@/lib/analytics';


interface TranscriptButtonGroupProps {
  transcriptCount: number;
  onCopyTranscript: () => void;
  onDownloadRecording: () => Promise<void>;
  onDiarize?: () => void;
  onStopDiarize?: () => void; // NEW
  diarizationStatus?: string;
  isDiarizing?: boolean;
  isRecording?: boolean;
}


export function TranscriptButtonGroup({
  transcriptCount,
  onCopyTranscript,
  onDownloadRecording,
  onDiarize,
  onStopDiarize,
  diarizationStatus,
  isDiarizing,
  isRecording
}: TranscriptButtonGroupProps) {
  const isProcessing = diarizationStatus === 'processing' || isDiarizing;

  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex gap-2">
        {onDiarize && (
          <Button
            size="sm"
            variant={isProcessing ? "destructive" : (diarizationStatus === 'completed' ? "outline" : "default")}
            className={isProcessing ? "" : (diarizationStatus === 'completed' ? "" : "bg-indigo-600 hover:bg-indigo-700 text-white")}
            onClick={isProcessing ? onStopDiarize : onDiarize}
            disabled={(!isProcessing && isRecording) || (!isProcessing && !onDiarize) || (isProcessing && !onStopDiarize)}
          >
            {isProcessing ? (
               // No spinner for Stop button usually, but here we want to show it's working until stopped?
               // Actually, "Stop" action should be immediate.
               <Users className="mr-2 h-4 w-4" /> 
            ) : (
               <Users className="mr-2 h-4 w-4" />
            )}
            <span className="hidden lg:inline">
              {isProcessing ? 'Stop Identification' :
                (diarizationStatus === 'completed' ? 'Re-identify Speakers' : 
                 (diarizationStatus === 'failed' ? 'Failed (Retry)' : 
                  (diarizationStatus === 'stopped' ? 'Stopped (Retry)' : 'Identify Speakers')))}
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
            Analytics.trackButtonClick('download_recording', 'meeting_details');
            onDownloadRecording();
          }}
          title="Download Audio File"
        >
          <Download className="h-4 w-4 lg:mr-2" />
          <span className="hidden lg:inline">Download Recording</span>
        </Button>
      </ButtonGroup>
    </div>
  );
}
