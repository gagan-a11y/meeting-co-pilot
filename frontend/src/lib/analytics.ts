
export interface AnalyticsProperties {
  [key: string]: string;
}

export interface DeviceInfo {
  platform: string;
  os_version: string;
  architecture: string;
}

export interface UserSession {
  session_id: string;
  user_id: string;
  start_time: string;
  last_heartbeat: string;
  is_active: boolean;
}

export class Analytics {
  private static initialized = false;
  private static currentUserId: string | null = null;

  static async init(): Promise<void> {
    console.log('[Analytics] Init (Stub)');
    this.initialized = true;
  }

  static async disable(): Promise<void> {
    console.log('[Analytics] Disable (Stub)');
    this.initialized = false;
  }

  static async isEnabled(): Promise<boolean> {
    return true;
  }

  static async track(eventName: string, properties?: AnalyticsProperties): Promise<void> {
    console.log('[Analytics] Track:', eventName, properties);
  }

  static async identify(userId: string, properties?: AnalyticsProperties): Promise<void> {
    console.log('[Analytics] Identify:', userId, properties);
    this.currentUserId = userId;
  }

  static async startSession(userId: string): Promise<string | null> {
    console.log('[Analytics] Start Session:', userId);
    return 'web-session-' + Date.now();
  }

  static async endSession(): Promise<void> {
    console.log('[Analytics] End Session');
  }

  static async trackDailyActiveUser(): Promise<void> {}
  static async trackUserFirstLaunch(): Promise<void> {}
  
  static async isSessionActive(): Promise<boolean> {
    return true;
  }

  static async getPersistentUserId(): Promise<string> {
    let userId = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('meeting_copilot_user_id') : null;
    if (!userId) {
      userId = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      if (typeof sessionStorage !== 'undefined') sessionStorage.setItem('meeting_copilot_user_id', userId);
    }
    return userId;
  }

  static async checkAndTrackFirstLaunch(): Promise<void> {}
  static async checkAndTrackDailyUsage(): Promise<void> {}

  static getCurrentUserId(): string | null {
    return this.currentUserId;
  }

  static async getPlatform(): Promise<string> {
    return 'Web';
  }

  static async getOSVersion(): Promise<string> {
    return 'Web';
  }

  static async getDeviceInfo(): Promise<DeviceInfo> {
    return {
      platform: 'Web',
      os_version: 'Web',
      architecture: 'unknown'
    };
  }

  static async calculateDaysSince(dateKey: string): Promise<number | null> {
    return 0;
  }

  static async updateMeetingCount(): Promise<void> {}
  static async getMeetingsCountToday(): Promise<number> { return 0; }
  static async hasUsedFeatureBefore(featureName: string): Promise<boolean> { return false; }
  static async markFeatureUsed(featureName: string): Promise<void> {}

  static async trackSessionStarted(sessionId: string): Promise<void> {}
  static async trackSessionEnded(sessionId: string): Promise<void> {}
  
  static async trackMeetingCompleted(meetingId: string, metrics: any): Promise<void> {
    console.log('[Analytics] Meeting Completed:', meetingId, metrics);
  }

  static async trackFeatureUsedEnhanced(featureName: string, properties?: Record<string, any>): Promise<void> {
    console.log('[Analytics] Feature Used:', featureName, properties);
  }

  static async trackCopy(copyType: 'transcript' | 'summary', properties?: Record<string, any>): Promise<void> {}

  static async trackMeetingStarted(meetingId: string, meetingTitle: string): Promise<void> {}
  static async trackRecordingStarted(meetingId: string): Promise<void> {}
  static async trackRecordingStopped(meetingId: string, durationSeconds?: number): Promise<void> {}
  static async trackMeetingDeleted(meetingId: string): Promise<void> {}
  static async trackSettingsChanged(settingType: string, newValue: string): Promise<void> {}
  static async trackFeatureUsed(featureName: string): Promise<void> {}
  
  static async trackPageView(pageName: string): Promise<void> {}
  static async trackButtonClick(buttonName: string, location?: string): Promise<void> {}
  static async trackError(errorType: string, errorMessage: string): Promise<void> {}
  static async trackAppStarted(): Promise<void> {}
  static async cleanup(): Promise<void> {}
  static reset(): void {}
  static async waitForInitialization(timeout: number = 5000): Promise<boolean> { return true; }
  static async trackBackendConnection(success: boolean, error?: string) {}
  static async trackTranscriptionError(errorMessage: string) {}
  static async trackTranscriptionSuccess(duration?: number) {}
  
  static async trackSummaryGenerationStarted(
    modelProvider: string,
    modelName: string,
    transcriptLength: number,
    timeSinceRecordingMinutes?: number
  ) {
    console.log('[Analytics] Summary Gen Started', { modelProvider, modelName });
  }

  static async trackSummaryGenerationCompleted(
    modelProvider: string, 
    modelName: string, 
    success: boolean, 
    durationSeconds?: number, 
    errorMessage?: string
  ) {
    console.log('[Analytics] Summary Gen Completed', { success, errorMessage });
  }

  static async trackSummaryRegenerated(modelProvider: string, modelName: string) {}

  static async trackModelChanged(oldProvider: string, oldModel: string, newProvider: string, newModel: string) {}

  static async trackCustomPromptUsed(length: number) {}
}

export default Analytics;