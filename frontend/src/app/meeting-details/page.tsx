"use client"
import { useSidebar } from "@/components/Sidebar/SidebarProvider";
import { useState, useEffect, useCallback, Suspense } from "react";
import { Transcript, Summary } from "@/types";
import PageContent from "./page-content";
import { useRouter, useSearchParams } from "next/navigation";
import Analytics from "@/lib/analytics";
import { LoaderIcon } from "lucide-react";
import { authFetch } from "@/lib/api";

interface MeetingDetailsResponse {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  transcripts: Transcript[];
}

function MeetingDetailsContent() {
  const searchParams = useSearchParams();
  const meetingId = searchParams.get('id');
  const { setCurrentMeeting, refetchMeetings, serverAddress } = useSidebar();
  const router = useRouter();
  const [meetingDetails, setMeetingDetails] = useState<MeetingDetailsResponse | null>(null);
  const [meetingSummary, setMeetingSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [shouldAutoGenerate, setShouldAutoGenerate] = useState<boolean>(false);
  const [hasCheckedAutoGen, setHasCheckedAutoGen] = useState<boolean>(false);

  // Check if gemma3:1b model is available in Ollama
  const checkForGemmaModel = useCallback(async (): Promise<boolean> => {
    try {
      const response = await fetch('http://localhost:11434/api/tags');
      if (!response.ok) throw new Error('Failed to fetch models');
      const data = await response.json();
      const models = data.models || [];
      const hasGemma = models.some((m: any) => m.name === 'gemma3:1b');
      console.log('🔍 Checked for gemma3:1b:', hasGemma);
      return hasGemma;
    } catch (error) {
      console.error('❌ Failed to check Ollama models:', error);
      return false;
    }
  }, []);

  // Set up auto-generation - respects DB as source of truth
  const setupAutoGeneration = useCallback(async () => {
    if (hasCheckedAutoGen) return; // Only check once

    try {
      if (!serverAddress) return;
      // ✅ STEP 1: Check what's currently in database
      const configResponse = await authFetch('/get-model-config');
      const currentConfig = await configResponse.json();

      // ✅ STEP 2: If DB already has a model, use it (never override!)
      if (currentConfig && currentConfig.model) {
        console.log('✅ Using existing model from DB:', currentConfig.model);
        setShouldAutoGenerate(true);
        setHasCheckedAutoGen(true);
        return;
      }

      // ✅ STEP 3: DB is empty - check if gemma3:1b exists as fallback
      const hasGemma = await checkForGemmaModel();

      if (hasGemma) {
        console.log('💾 DB empty, using gemma3:1b as initial default');

        await authFetch('/save-model-config', {
          method: 'POST',
          body: JSON.stringify({
            provider: 'ollama',
            model: 'gemma3:1b',
            whisperModel: 'large-v3',
            apiKey: null
          })
        });

        setShouldAutoGenerate(true);
      } else {
        console.log('⚠️ No model configured and gemma3:1b not found');
      }
    } catch (error) {
      console.error('❌ Failed to setup auto-generation:', error);
    }

    setHasCheckedAutoGen(true);
  }, [hasCheckedAutoGen, checkForGemmaModel, serverAddress]);

  // Extract fetchMeetingDetails so it can be called from child components
  const fetchMeetingDetails = useCallback(async () => {
    if (!meetingId || meetingId === 'intro-call' || !serverAddress) {
      return;
    }

    try {
      const response = await authFetch(`/get-meeting/${meetingId}`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      console.log('Meeting details:', data);
      setMeetingDetails(data);
      setCurrentMeeting({ id: data.id, title: data.title });
    } catch (error) {
      console.error('Error fetching meeting details:', error);
      setError("Failed to load meeting details");
    }
  }, [meetingId, setCurrentMeeting, serverAddress]);

  const fetchMeetingSummary = useCallback(async () => {
    if (!meetingId || meetingId === 'intro-call' || !serverAddress) return;
    try {
      const response = await authFetch(`/get-summary/${meetingId}`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const summary = await response.json();
      console.log('🔍 FETCH SUMMARY: Raw response:', summary);

      if (summary.status === 'error' || summary.error || summary.status === 'idle') {
        setMeetingSummary(null);
        return;
      }

      const summaryData = summary.data || {};
      let parsedData = summaryData;
      if (typeof summaryData === 'string') {
        try {
          parsedData = JSON.parse(summaryData);
        } catch (e) {
          parsedData = {};
        }
      }

      if (parsedData.summary_json || parsedData.markdown) {
        setMeetingSummary(parsedData as any);
        return;
      }

      // Legacy format handling
      const { MeetingName, _section_order, ...restSummaryData } = parsedData;
      const formattedSummary: Summary = {};
      const sectionKeys = _section_order || Object.keys(restSummaryData);

      for (const key of sectionKeys) {
        const section = restSummaryData[key];
        if (section && typeof section === 'object' && 'title' in section && 'blocks' in section) {
          formattedSummary[key] = {
            title: section.title || key,
            blocks: Array.isArray(section.blocks) ? section.blocks.map((block: any) => ({
              ...block,
              color: 'default',
              content: block?.content?.trim() || ''
            })) : []
          };
        }
      }
      setMeetingSummary(formattedSummary);
    } catch (error) {
      console.error('❌ FETCH SUMMARY Error:', error);
      setMeetingSummary(null);
    }
  }, [meetingId, serverAddress]);

  const handleMeetingUpdated = useCallback(async () => {
    await fetchMeetingDetails();
    await fetchMeetingSummary();
    await refetchMeetings();
  }, [fetchMeetingDetails, fetchMeetingSummary, refetchMeetings]);

  // Reset states when meetingId changes
  useEffect(() => {
    setMeetingDetails(null);
    setMeetingSummary(null);
    setError(null);
    setIsLoading(true);
  }, [meetingId]);

  // Initial load
  useEffect(() => {
    if (!meetingId || meetingId === 'intro-call') {
      setError("No meeting selected");
      setIsLoading(false);
      return;
    }

    const loadData = async () => {
      if (!serverAddress) return;
      try {
        await Promise.all([
          fetchMeetingDetails(),
          fetchMeetingSummary()
        ]);
      } finally {
        setIsLoading(false);
      }
    };

    if (serverAddress) {
      loadData();
    }
  }, [meetingId, fetchMeetingDetails, fetchMeetingSummary, serverAddress]);

  // Poll for summary if missing
  useEffect(() => {
    if (meetingDetails && meetingSummary === null && (meetingDetails.transcripts?.length || 0) > 0) {
      const pollInterval = setInterval(async () => {
        try {
          if (!serverAddress) return;
          const response = await authFetch(`/get-summary/${meetingId}`);
          if (response.ok) {
            const summary = await response.json();
            if (summary.status === 'completed' && summary.data) {
              clearInterval(pollInterval);
              await fetchMeetingSummary();
            } else if (summary.status === 'error') {
              clearInterval(pollInterval);
            }
          }
        } catch (error) {
          console.error('Error polling summary:', error);
        }
      }, 5000);

      const timeout = setTimeout(() => {
        clearInterval(pollInterval);
      }, 180000);

      return () => {
        clearInterval(pollInterval);
        clearTimeout(timeout);
      };
    }
  }, [meetingDetails, meetingSummary, meetingId, serverAddress, fetchMeetingSummary]);

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-red-500 mb-4">{error}</p>
          <button onClick={() => router.push('/')} className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">
            Go Back
          </button>
        </div>
      </div>
    );
  }

  if (isLoading || !meetingDetails) {
    return <div className="flex items-center justify-center h-screen"><LoaderIcon className="animate-spin size-6" /></div>;
  }

  return <PageContent
    meeting={meetingDetails}
    summaryData={meetingSummary}
    shouldAutoGenerate={shouldAutoGenerate}
    onAutoGenerateComplete={() => setShouldAutoGenerate(false)}
    onMeetingUpdated={handleMeetingUpdated}
  />;
}

export default function MeetingDetails() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-screen"><LoaderIcon className="animate-spin size-6" /></div>}>
      <MeetingDetailsContent />
    </Suspense>
  );
}
