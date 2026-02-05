import { Transcript } from '@/types';

const DB_NAME = 'MeetingCopilotRecovery';
const STORE_NAME = 'pending_transcripts';
const DB_VERSION = 1;

export interface PendingMeetingData {
  meetingId: string; // generated or actual ID
  title: string;
  transcripts: Transcript[];
  timestamp: number; // when it was saved locally
  templateId?: string;
  sessionId?: string | null; // ID of the audio recording session
}

class TranscriptRecoveryService {
  private dbPromise: Promise<IDBDatabase> | null = null;

  private async getDB(): Promise<IDBDatabase> {
    if (this.dbPromise) return this.dbPromise;

    this.dbPromise = new Promise((resolve, reject) => {
      if (typeof window === 'undefined') {
        reject(new Error('IndexedDB is not available server-side'));
        return;
      }

      const request = window.indexedDB.open(DB_NAME, DB_VERSION);

      request.onerror = () => {
        console.error('Failed to open recovery database');
        reject(request.error);
      };

      request.onsuccess = () => {
        resolve(request.result);
      };

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: 'meetingId' });
        }
      };
    });

    return this.dbPromise;
  }

  async savePendingTranscript(data: PendingMeetingData): Promise<void> {
    try {
      const db = await this.getDB();
      return new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE_NAME, 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.put(data);

        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });
    } catch (error) {
      console.error('Failed to save pending transcript:', error);
      throw error;
    }
  }

  async getPendingTranscript(meetingId: string): Promise<PendingMeetingData | undefined> {
    try {
      const db = await this.getDB();
      return new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE_NAME, 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.get(meetingId);

        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
    } catch (error) {
      console.error('Failed to get pending transcript:', error);
      return undefined;
    }
  }

  async getAllPendingTranscripts(): Promise<PendingMeetingData[]> {
    try {
      const db = await this.getDB();
      return new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE_NAME, 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.getAll();

        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
      });
    } catch (error) {
      console.error('Failed to get all pending transcripts:', error);
      return [];
    }
  }

  async deletePendingTranscript(meetingId: string): Promise<void> {
    try {
      const db = await this.getDB();
      return new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE_NAME, 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.delete(meetingId);

        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });
    } catch (error) {
      console.error('Failed to delete pending transcript:', error);
      throw error;
    }
  }
}

export const recoveryService = new TranscriptRecoveryService();
