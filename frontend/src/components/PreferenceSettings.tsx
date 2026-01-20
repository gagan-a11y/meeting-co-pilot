"use client"

import { useEffect, useState } from "react"
import { Switch } from "./ui/switch"
import { FolderOpen } from "lucide-react"
import Analytics from "@/lib/analytics"
import AnalyticsConsentSwitch from "./AnalyticsConsentSwitch"
import { toast } from "sonner"

interface StorageLocations {
  database: string
  models: string
  recordings: string
}

interface NotificationSettings {
  recording_notifications: boolean
  time_based_reminders: boolean
  meeting_reminders: boolean
  respect_do_not_disturb: boolean
  notification_sound: boolean
  system_permission_granted: boolean
  consent_given: boolean
  manual_dnd_mode: boolean
  notification_preferences: {
    show_recording_started: boolean
    show_recording_stopped: boolean
    show_recording_paused: boolean
    show_recording_resumed: boolean
    show_transcription_complete: boolean
    show_meeting_reminders: boolean
    show_system_errors: boolean
    meeting_reminder_minutes: number[]
  }
}

export function PreferenceSettings() {
  const [notificationsEnabled, setNotificationsEnabled] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [storageLocations, setStorageLocations] = useState<StorageLocations>({
    database: 'Server Managed',
    models: 'Server Managed',
    recordings: 'Browser Downloads'
  });

  useEffect(() => {
    const loadPreferences = () => {
      try {
        const storedEnabled = localStorage.getItem('notifications_enabled');
        setNotificationsEnabled(storedEnabled !== 'false');

        // Track preferences page view
        Analytics.track('preferences_viewed', {
          notifications_enabled: storedEnabled !== 'false' ? 'true' : 'false'
        });
      } catch (error) {
        console.error('Failed to load preferences:', error);
      } finally {
        setLoading(false);
      }
    };

    loadPreferences();
  }, [])

  useEffect(() => {
    if (loading || notificationsEnabled === null) return;

    localStorage.setItem('notifications_enabled', String(notificationsEnabled));

    // Track notification preference change
    Analytics.track('notification_settings_changed', {
      notifications_enabled: notificationsEnabled.toString()
    });

  }, [notificationsEnabled, loading])

  const handleOpenFolder = (folderType: 'recordings') => {
    toast.info('Recordings are available in your browser downloads or the Meeting Details page.');
  };

  if (loading || notificationsEnabled === null) {
    return <div className="max-w-2xl mx-auto p-6">Loading Preferences...</div>
  }

  return (
    <div className="space-y-6">
      {/* Notifications Section */}
      <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Notifications</h3>
            <p className="text-sm text-gray-600">Enable or disable notifications of start and end of meeting</p>
          </div>
          <Switch checked={notificationsEnabled} onCheckedChange={setNotificationsEnabled} />
        </div>
      </div>

      {/* Data Storage Locations Section */}
      <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Data Storage Locations</h3>
        <p className="text-sm text-gray-600 mb-6">
          View and access where Pnyx stores your data
        </p>

        <div className="space-y-4">
          {/* Recordings Location */}
          <div className="p-4 border rounded-lg bg-gray-50">
            <div className="font-medium mb-2">Meeting Recordings</div>
            <div className="text-sm text-gray-600 mb-3 break-all font-mono text-xs">
              {storageLocations.recordings}
            </div>
            <button
              onClick={() => handleOpenFolder('recordings')}
              className="flex items-center gap-2 px-3 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-100 transition-colors"
            >
              <FolderOpen className="w-4 h-4" />
              Open Folder
            </button>
          </div>
        </div>

        <div className="mt-4 p-3 bg-blue-50 rounded-md">
          <p className="text-xs text-blue-800">
            <strong>Note:</strong> Data is stored securely on the server.
          </p>
        </div>
      </div>

      {/* Analytics Section */}
      <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
        <AnalyticsConsentSwitch />
      </div>
    </div>
  )
}
