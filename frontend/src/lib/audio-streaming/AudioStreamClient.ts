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

export class AudioStreamClient {
  private audioContext: AudioContext | null = null;
  private audioWorklet: AudioWorkletNode | null = null;
  private websocket: WebSocket | null = null;
  private mediaStream: MediaStream | null = null;
  private callbacks: StreamingCallbacks = {};
  private isStreaming: boolean = false;

  constructor(
    private wsUrl: string = 'ws://localhost:5167/ws/streaming-audio'
  ) {}

  /**
   * Start streaming audio to backend
   */
  async start(callbacks: StreamingCallbacks): Promise<void> {
    if (this.isStreaming) {
      console.warn('[AudioStream] Already streaming');
      return;
    }

    this.callbacks = callbacks;

    try {
      console.log('[AudioStream] Starting...');

      // 1. Get microphone access (let browser use native sample rate)
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1    // Mono
          // DON'T specify sampleRate - let browser use native rate
        }
      });

      console.log('[AudioStream] ✅ Microphone access granted');

      // 2. Create AudioContext with native sample rate first
      // We'll resample in the worklet if needed
      this.audioContext = new AudioContext();

      // 3. Load AudioWorklet processor
      await this.audioContext.audioWorklet.addModule('/audio-processor.worklet.js');
      console.log('[AudioStream] ✅ AudioWorklet loaded');

      // 4. Connect WebSocket BEFORE starting audio
      await this.connectWebSocket();

      // 5. Create worklet node with sample rate info
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.audioWorklet = new AudioWorkletNode(
        this.audioContext,
        'audio-stream-processor',
        {
          processorOptions: {
            sampleRate: this.audioContext.sampleRate
          }
        }
      );

      console.log(`[AudioStream] Audio pipeline: ${this.audioContext.sampleRate}Hz → 16kHz`);

      // 6. Handle audio data from worklet
      this.audioWorklet.port.onmessage = (event) => {
        if (this.websocket?.readyState === WebSocket.OPEN) {
          // Send PCM data to backend
          this.websocket.send(event.data);
        }
      };

      // 7. Connect audio graph (but NOT to speakers)
      source.connect(this.audioWorklet);
      // DO NOT connect to destination - we don't want to hear ourselves!

      this.isStreaming = true;
      console.log('[AudioStream] ✅ Streaming started successfully');

    } catch (error) {
      console.error('[AudioStream] ❌ Failed to start:', error);
      this.cleanup();
      this.callbacks.onError?.(error as Error);
      throw error;
    }
  }

  /**
   * Connect to WebSocket backend
   */
  private async connectWebSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      console.log(`[AudioStream] Connecting to ${this.wsUrl}...`);

      this.websocket = new WebSocket(this.wsUrl);
      this.websocket.binaryType = 'arraybuffer';

      // Connection timeout (10 seconds)
      const timeout = setTimeout(() => {
        if (this.websocket?.readyState !== WebSocket.OPEN) {
          this.websocket?.close();
          reject(new Error('WebSocket connection timeout'));
        }
      }, 10000);

      this.websocket.onopen = () => {
        clearTimeout(timeout);
        console.log('[AudioStream] ✅ WebSocket connected');
      };

      this.websocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          switch (data.type) {
            case 'connected':
              console.log(`[AudioStream] ✅ Session ${data.session_id} ready`);
              this.callbacks.onConnected?.(data.session_id);
              resolve();
              break;

            case 'partial':
              this.callbacks.onPartial?.(
                data.text,
                data.confidence,
                data.is_stable
              );
              break;

            case 'final':
              this.callbacks.onFinal?.(
                data.text,
                data.confidence,
                data.reason
              );
              break;

            case 'error':
              console.error('[AudioStream] Backend error:', data.message);
              this.callbacks.onError?.(new Error(data.message));
              break;

            default:
              console.warn('[AudioStream] Unknown message type:', data.type);
          }
        } catch (error) {
          console.error('[AudioStream] Failed to parse message:', error);
        }
      };

      this.websocket.onerror = (error) => {
        clearTimeout(timeout);
        console.error('[AudioStream] WebSocket error:', error);
        reject(error);
      };

      this.websocket.onclose = (event) => {
        console.log(`[AudioStream] WebSocket closed (code: ${event.code})`);
        this.callbacks.onDisconnected?.();
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
