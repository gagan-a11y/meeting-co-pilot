import { useCallback } from 'react';
import { toast } from 'sonner';
import { useSidebar } from '@/components/Sidebar/SidebarProvider';

interface UseMeetingOperationsProps {
  meeting: any;
}

export function useMeetingOperations({
  meeting,
}: UseMeetingOperationsProps) {
  const { serverAddress } = useSidebar();
  const baseUrl = serverAddress || 'http://localhost:5167';

  // Open meeting folder in file explorer
  const handleOpenMeetingFolder = useCallback(async () => {
    try {
      // Web app cannot access local file system directly to open folders
      toast.info('Feature not available in web version', {
        description: 'Opening local folders is not supported in the browser.'
      });
    } catch (error) {
      console.error('Failed to open meeting folder:', error);
      toast.error(error as string || 'Failed to open recording folder');
    }
  }, [meeting.id]);

  // Delete meeting
  const handleDeleteMeeting = useCallback(async (router: any) => {
    try {
      if (!confirm('Are you sure you want to delete this meeting? This action cannot be undone.')) {
        return;
      }

      const response = await fetch(`${baseUrl}/delete-meeting`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meeting_id: meeting.id }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Failed to delete meeting');
      }

      toast.success('Meeting deleted successfully');
      // Redirect to home page
      router.push('/');
      
    } catch (error) {
      console.error('Failed to delete meeting:', error);
      toast.error('Failed to delete meeting', { 
        description: error instanceof Error ? error.message : 'Unknown error'
      });
    }
  }, [meeting.id, baseUrl]);

  return {
    handleOpenMeetingFolder,
    handleDeleteMeeting,
  };
}
