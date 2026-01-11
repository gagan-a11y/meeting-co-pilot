"use client";
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Summary, SummaryResponse } from '@/types';
import { useSidebar } from '@/components/Sidebar/SidebarProvider';
import Analytics from '@/lib/analytics';
import { TranscriptPanel } from '@/components/MeetingDetails/TranscriptPanel';
import { SummaryPanel } from '@/components/MeetingDetails/SummaryPanel';
import { ChatInterface } from '@/components/MeetingDetails/ChatInterface';
import { Bot, MessageSquare } from 'lucide-react';

// Custom hooks
import { useMeetingData } from '@/hooks/meeting-details/useMeetingData';
import { useSummaryGeneration } from '@/hooks/meeting-details/useSummaryGeneration';
import { useModelConfiguration } from '@/hooks/meeting-details/useModelConfiguration';
import { useTemplates } from '@/hooks/meeting-details/useTemplates';
import { useCopyOperations } from '@/hooks/meeting-details/useCopyOperations';
import { useMeetingOperations } from '@/hooks/meeting-details/useMeetingOperations';

import { useRouter } from 'next/navigation';

export default function PageContent({
  meeting,
  summaryData,
  shouldAutoGenerate = false,
  onAutoGenerateComplete,
  onMeetingUpdated
}: {
  meeting: any;
  summaryData: Summary | null;
  shouldAutoGenerate?: boolean;
  onAutoGenerateComplete?: () => void;
  onMeetingUpdated?: () => Promise<void>;
}) {
  const router = useRouter(); // Initialize router

  console.log('📄 PAGE CONTENT: Initializing with data:', {
    meetingId: meeting.id,
    summaryDataKeys: summaryData ? Object.keys(summaryData) : null,
    transcriptsCount: meeting.transcripts?.length
  });

  // State
  const [customPrompt, setCustomPrompt] = useState<string>('');
  const [isRecording] = useState(false);
  const [summaryResponse] = useState<SummaryResponse | null>(null);
  const [isChatOpen, setIsChatOpen] = useState(false);

  // Sidebar context
  const { serverAddress } = useSidebar();

  // Custom hooks
  const meetingData = useMeetingData({ meeting, summaryData, onMeetingUpdated });
  const modelConfig = useModelConfiguration({ serverAddress });
  const templates = useTemplates();

  const summaryGeneration = useSummaryGeneration({
    meeting,
    transcripts: meetingData.transcripts,
    modelConfig: modelConfig.modelConfig,
    isModelConfigLoading: modelConfig.isLoading,
    selectedTemplate: templates.selectedTemplate,
    onMeetingUpdated,
    updateMeetingTitle: meetingData.updateMeetingTitle,
    setAiSummary: meetingData.setAiSummary,
  });

  const copyOperations = useCopyOperations({
    meeting,
    transcripts: meetingData.transcripts,
    meetingTitle: meetingData.meetingTitle,
    aiSummary: meetingData.aiSummary,
    blockNoteSummaryRef: meetingData.blockNoteSummaryRef,
  });

  const meetingOperations = useMeetingOperations({
    meeting,
  });

  // Track page view
  useEffect(() => {
    Analytics.trackPageView('meeting_details');
  }, []);

  // Track if initial generation has been triggered
  const [hasTriggeredInitialGeneration, setHasTriggeredInitialGeneration] = useState(false);

  // Auto-generate notes on page load when transcripts exist but no summary
  useEffect(() => {
    const transcriptsExist = meetingData.transcripts && meetingData.transcripts.length > 0;
    const noSummaryExists = !meetingData.aiSummary;
    const notProcessing = summaryGeneration.summaryStatus === 'idle' || summaryGeneration.summaryStatus === 'error';
    const modelReady = !modelConfig.isLoading && modelConfig.modelConfig.provider;

    if (transcriptsExist && noSummaryExists && notProcessing && modelReady && !hasTriggeredInitialGeneration) {
      console.log('🚀 Auto-generating notes on page load with template:', templates.selectedTemplate);
      setHasTriggeredInitialGeneration(true);
      // Slight delay to ensure everything is ready
      setTimeout(() => {
        summaryGeneration.handleGenerateSummary('');
      }, 500);
    }
  }, [
    meetingData.transcripts,
    meetingData.aiSummary,
    summaryGeneration.summaryStatus,
    modelConfig.isLoading,
    modelConfig.modelConfig.provider,
    templates.selectedTemplate,
    hasTriggeredInitialGeneration,
    summaryGeneration.handleGenerateSummary
  ]);

  // Auto-regenerate notes when template changes
  useEffect(() => {
    if (templates.templateChanged && meetingData.transcripts && meetingData.transcripts.length > 0) {
      console.log('🔄 Template changed, regenerating notes with:', templates.selectedTemplate);
      // Clear the current summary to show loading state
      meetingData.setAiSummary(null);
      // Trigger regeneration
      setTimeout(() => {
        summaryGeneration.handleGenerateSummary('');
        templates.acknowledgeTemplateChange();
      }, 100);
    }
  }, [
    templates.templateChanged,
    templates.selectedTemplate,
    templates.acknowledgeTemplateChange,
    meetingData.transcripts,
    meetingData.setAiSummary,
    summaryGeneration.handleGenerateSummary
  ]);

  // Poll for summary if processing (notes are generating)
  useEffect(() => {
    if (summaryGeneration.summaryStatus === 'processing' || summaryGeneration.summaryStatus === 'summarizing') {
      const pollInterval = setInterval(async () => {
        console.log(`🔄 Polling for summary for meeting ${meeting.id}...`);
        if (onMeetingUpdated) {
          await onMeetingUpdated();
        }
      }, 3000); // Poll every 3 seconds

      // Stop polling after 2 minutes
      const timeout = setTimeout(() => {
        clearInterval(pollInterval);
      }, 120000);

      return () => {
        clearInterval(pollInterval);
        clearTimeout(timeout);
      };
    }
  }, [meeting.id, summaryGeneration.summaryStatus, onMeetingUpdated]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="flex flex-col h-screen bg-gray-50"
    >
      <div className="flex flex-1 overflow-hidden">


        <TranscriptPanel
          transcripts={meetingData.transcripts}
          customPrompt={customPrompt}
          onPromptChange={setCustomPrompt}
          onCopyTranscript={copyOperations.handleCopyTranscript}
          onOpenMeetingFolder={meetingOperations.handleOpenMeetingFolder}
          isRecording={isRecording}
        />

        <SummaryPanel
          meeting={meeting}
          meetingTitle={meetingData.meetingTitle}
          onTitleChange={meetingData.handleTitleChange}
          isEditingTitle={meetingData.isEditingTitle}
          onStartEditTitle={() => meetingData.setIsEditingTitle(true)}
          onFinishEditTitle={() => meetingData.setIsEditingTitle(false)}
          isTitleDirty={meetingData.isTitleDirty}
          summaryRef={meetingData.blockNoteSummaryRef}
          isSaving={meetingData.isSaving}
          onSaveAll={meetingData.saveAllChanges}
          onCopySummary={copyOperations.handleCopySummary}
          onOpenFolder={meetingOperations.handleOpenMeetingFolder}
          aiSummary={meetingData.aiSummary}
          summaryStatus={summaryGeneration.summaryStatus}
          transcripts={meetingData.transcripts}
          modelConfig={modelConfig.modelConfig}
          setModelConfig={modelConfig.setModelConfig}
          onSaveModelConfig={modelConfig.handleSaveModelConfig}
          onGenerateSummary={summaryGeneration.handleGenerateSummary}
          customPrompt={customPrompt}
          summaryResponse={summaryResponse}
          onSaveSummary={meetingData.handleSaveSummary}
          onSummaryChange={meetingData.handleSummaryChange}
          onDirtyChange={meetingData.setIsSummaryDirty}
          summaryError={summaryGeneration.summaryError}
          onRegenerateSummary={summaryGeneration.handleRegenerateSummary}
          getSummaryStatusMessage={summaryGeneration.getSummaryStatusMessage}
          availableTemplates={templates.availableTemplates}
          selectedTemplate={templates.selectedTemplate}
          onTemplateSelect={templates.handleTemplateSelection}
          isModelConfigLoading={modelConfig.isLoading}
          onDeleteMeeting={() => meetingOperations.handleDeleteMeeting(router)}
        />

      </div>

      {/* Chat Interface */}
      {isChatOpen && (
        <ChatInterface
          meetingId={meeting.id}
          onClose={() => setIsChatOpen(false)}
          currentTranscripts={meetingData.transcripts}
        />
      )}

      {/* Floating Chat Button */}
      {!isChatOpen && (
        <motion.button
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
          onClick={() => setIsChatOpen(true)}
          className="fixed bottom-6 right-6 p-4 bg-blue-600 text-white rounded-full shadow-lg hover:bg-blue-700 transition-colors z-40 flex items-center gap-2"
        >
          <Bot className="w-6 h-6" />
          <span className="font-medium">Ask AI</span>
        </motion.button>
      )}
    </motion.div>
  );
}
