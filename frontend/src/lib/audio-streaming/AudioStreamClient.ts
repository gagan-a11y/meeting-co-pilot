/**
 * Audio Stream Client for Real-Time Transcription
 *
 * Manages: Microphone → AudioWorklet → WebSocket → Backend
 *
 * Features:
 * - Continuous PCM audio streaming
 * - WebSocket connection management
 * - Partial and final transcript handling
 */

export interface StreamingCallbacks {
  onPartial?: (text: string, confidence: number, isStable: boolean) => void;
  onFinal?: (text: string, confidence: number, reason: string) => void;
  onError?: (error: Error) => void;
  onConnected?: (sessionId: string) => void;
  onDisconnected?: () => void;
}

import { wsUrl } from '../config';

export class AudioStreamClient {
  private audioContext: AudioContext | null = null;
  private audioWorklet: AudioWorkletNode | null = null;
  private websocket: WebSocket | null = null;
  private mediaStream: MediaStream | null = null;
  private callbacks: StreamingCallbacks = {};
  private isStreaming: boolean = false;

  // Robustness state
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 5;
  private audioQueue: Float32Array[] = [];
  private isReconnecting: boolean = false;
  private sessionId: string | null = null;
  private userEmail: string | null = null;

  constructor(
    private wsUrlOverride: string = wsUrl
  ) {}

  /**
   * Start streaming audio to backend
   */
  async start(callbacks: StreamingCallbacks, userEmail?: string): Promise<void> {
    if (this.isStreaming) return;

    this.callbacks = callbacks;
    this.reconnectAttempts = 0;
    this.audioQueue = []; // Clear queue on fresh start
    this.sessionId = null; // Clear session on fresh start
    this.userEmail = userEmail || null;

    try {
      console.log('[AudioStream] Starting pipeline...');

      // 1. Get microphone access
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1
        }
      });

      // 2. Setup Audio Context & Worklet
      this.audioContext = new AudioContext();
      await this.audioContext.audioWorklet.addModule('/audio-processor.worklet.js');
      
      // 3. Connect WebSocket (with retry capability)
      await this.connectWithRetry();

      // 4. Create pipeline
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.audioWorklet = new AudioWorkletNode(
        this.audioContext,
        'audio-stream-processor',
        { processorOptions: { sampleRate: this.audioContext.sampleRate } }
      );

      // 5. Handle audio data
      this.audioWorklet.port.onmessage = (event) => {
        // If connected, send immediately
        if (this.websocket?.readyState === WebSocket.OPEN) {
          this.flushQueue(); // Send any buffered data first
          this.websocket.send(event.data);
        } else {
          // If disconnected, buffer the audio
          // Note: event.data is Float32Array or similar, verify format
          // AudioWorklet usually sends Float32Array. If we need ArrayBuffer:
          this.audioQueue.push(event.data);
          
          if (this.audioQueue.length % 50 === 0) {
            console.warn(`[AudioStream] Buffering... Queue size: ${this.audioQueue.length}`);
          }
        }
      };

      source.connect(this.audioWorklet);
      this.isStreaming = true;
      console.log('[AudioStream] ✅ Streaming started');

    } catch (error) {
      console.error('[AudioStream] Start failed:', error);
      this.cleanup();
      throw error;
    }
  }

  private flushQueue() {
    if (this.audioQueue.length > 0 && this.websocket?.readyState === WebSocket.OPEN) {
      console.log(`[AudioStream] 🔄 Flushing ${this.audioQueue.length} buffered chunks`);
      while (this.audioQueue.length > 0) {
        const chunk = this.audioQueue.shift();
        if (chunk) this.websocket.send(chunk);
      }
    }
  }

  private async connectWithRetry(): Promise<void> {
    try {
      await this.connectWebSocket();
      this.reconnectAttempts = 0; // Reset on success
      this.isReconnecting = false;
      this.flushQueue();
    } catch (error) {
       if (this.reconnectAttempts < this.maxReconnectAttempts) {
         this.isReconnecting = true;
         this.reconnectAttempts++;
         const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 5000);
         console.warn(`[AudioStream] Connection failed. Retrying in ${delay}ms (Attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
         
         await new Promise(r => setTimeout(r, delay));
         return this.connectWithRetry();
       } else {
         console.error('[AudioStream] Max retries reached. Giving up.');
         this.callbacks.onError?.(new Error('Connection lost. Please refresh.'));
         throw error;
       }
    }
  }

  private async connectWebSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      // Append session_id if we have one (for resuming)
      let url = this.sessionId 
        ? `${this.wsUrlOverride}?session_id=${this.sessionId}`
        : this.wsUrlOverride;
        
      if (this.userEmail) {
        url += (url.includes('?') ? '&' : '?') + `user_email=${encodeURIComponent(this.userEmail)}`;
      }
        
      this.websocket = new WebSocket(url);
      this.websocket.binaryType = 'arraybuffer';

      const timeout = setTimeout(() => {
        if (this.websocket?.readyState !== WebSocket.OPEN) {
          this.websocket?.close();
          reject(new Error('Timeout'));
        }
      }, 5000);

      this.websocket.onopen = () => {
        clearTimeout(timeout);
        console.log('[AudioStream] WebSocket connected');
        resolve();
      };

      this.websocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'connected') {
            console.log(`[AudioStream] ✅ Session ${data.session_id} ready`);
            this.sessionId = data.session_id; // Store for reconnection
            this.callbacks.onConnected?.(data.session_id);
          }
          else if (data.type === 'partial') this.callbacks.onPartial?.(data.text, data.confidence, data.is_stable);
          else if (data.type === 'final') this.callbacks.onFinal?.(data.text, data.confidence, data.reason);
          else if (data.type === 'error') this.callbacks.onError?.(new Error(data.message));
        } catch (e) {
          console.error('Parse error', e);
        }
      };

      this.websocket.onclose = (event) => {
        console.log(`[AudioStream] WebSocket closed: ${event.code}`);
        // If we were streaming and didn't close intentionally, try to reconnect
        if (this.isStreaming && !event.wasClean) {
             this.connectWithRetry().catch(() => {
                 this.stop(); // Give up if retry fails
             });
        }
      };

      this.websocket.onerror = (err) => {
        // Just log, onclose will handle logic
        console.error('[AudioStream] WS Error:', err);
      };
    });
  }

  /**
   * Stop streaming
   */
  stop(): void {
    console.log('[AudioStream] Stopping...');
    this.isStreaming = false;
    this.cleanup();
    console.log('[AudioStream] ✅ Stopped');
  }

  /**
   * Cleanup all resources
   */
  private cleanup(): void {
    // Stop audio worklet
    if (this.audioWorklet) {
      this.audioWorklet.disconnect();
      this.audioWorklet = null;
    }

    // Close audio context
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }

    // Stop media stream
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }

    // Close WebSocket
    if (this.websocket) {
      this.websocket.close();
      this.websocket = null;
    }
  }

  /**
   * Get current streaming status
   */
  isActive(): boolean {
    return this.isStreaming &&
           this.websocket?.readyState === WebSocket.OPEN &&
           this.audioContext?.state === 'running';
  }
}
