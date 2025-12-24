# Phase 1: Tauri Removal + Web Audio Implementation

**Target Duration**: 5-7 working days
**Approach**: ⭐ **Incremental Migration** (Build new system alongside old, then swap)
**Goal**: Remove Tauri dependencies and implement browser-based audio capture with WebSocket streaming to backend

---

## Migration Strategy: Why Incremental?

### ❌ Alternative: "Big Bang" 
```
Day 1-2: Delete Tauri → App completely broken ❌
Day 3-4: Build browser audio → Still broken ❌
Day 5-6: Build WebSocket → Finally works ✅
Day 7: Test and hope nothing breaks 🤞
```
**Risk**: High - Can't test until Day 5-6, hard to debug, no rollback option

### ✅ Our Approach: Incremental Migration 
```
Day 1: Build browser audio (NEW files, Tauri untouched) ✅
Day 2: Build backend WebSocket (NEW endpoint, Tauri untouched) ✅
Day 3: Test new system end-to-end (Tauri still working) ✅
       🎉 CONFIDENCE CHECKPOINT: New system proven working
Day 4: Switch main app to use new system (old code kept as backup) 🔄
Day 5: Remove Tauri safely (new system confirmed working) 🗑️
Day 6-7: Polish and production-ready ✨
```
**Benefits**: Lower risk, incremental testing, easy rollback, confidence building

---

## Executive Summary

### Current Architecture (Meetily - Desktop)
```
┌─────────────────────────────────────────┐
│   Frontend (Tauri Desktop App)          │
│  ┌──────────┐  ┌────────────────────┐  │
│  │ Next.js  │←→│  Rust (Audio/IPC)  │  │
│  │   UI     │  │   - Device capture │  │
│  │          │  │   - VAD detection  │  │
│  │          │  │   - WAV encoding   │  │
│  └──────────┘  └────────────────────┘  │
│       ↑ Tauri Events (invoke/listen)    │
└───────┼─────────────────────────────────┘
        │ HTTP POST (WAV file)
        ↓
┌───────────────────────────────────────┐
│   Whisper.cpp Server (Port 8178)     │
│  - Receives WAV files via HTTP       │
│  - Returns transcript text           │
└───────────────────────────────────────┘
        ↓
┌───────────────────────────────────────┐
│   FastAPI Backend (Port 5167)        │
│  - Saves transcripts to SQLite       │
│  - LLM processing (Claude/Ollama)    │
│  - No WebSocket support currently    │
└───────────────────────────────────────┘
```

### Target Architecture (Meeting Co-Pilot - Web)
```
┌─────────────────────────────────────────┐
│   Frontend (Pure Web - Next.js)         │
│  ┌──────────────────────────────────┐  │
│  │   Browser Audio Capture          │  │
│  │   - getUserMedia()               │  │
│  │   - MediaRecorder API            │  │
│  │   - AudioContext (processing)    │  │
│  └──────────────────────────────────┘  │
│       ↓ WebSocket (Binary chunks)       │
└───────┼─────────────────────────────────┘
        │
        ↓
┌───────────────────────────────────────┐
│   FastAPI Backend (Port 5167)        │
│  NEW: WebSocket endpoint             │
│  - Receive audio chunks              │
│  - Forward to Whisper via HTTP       │
│  - Broadcast transcript to clients   │
└───────────────────────────────────────┘
        ↓ HTTP POST (WAV chunks)
┌───────────────────────────────────────┐
│   Whisper.cpp Server (Port 8178)     │
│  - Process audio chunks              │
│  - Return transcript text            │
└───────────────────────────────────────┘
```

---

## Phase 1 Implementation Plan (Incremental)

### Day 1: Build Browser Audio Capture (Tauri Untouched) 🎙️

**Status**: Main app still uses Tauri (works normally)
**Objective**: Prove browser can capture audio independently

#### Tasks:

**1. Create New Audio Module** (don't modify existing files)

```bash
# Create new directory structure
mkdir -p frontend/src/lib/audio-web/
```

**File**: `frontend/src/lib/audio-web/capture.ts` (NEW)

```typescript
/**
 * Browser-based audio capture using MediaRecorder API
 * Built alongside existing Tauri system for safe migration
 */

export class WebAudioCapture {
  private mediaStream: MediaStream | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;

  /**
   * Request microphone permission and start capture
   */
  async start(deviceId?: string): Promise<void> {
    const constraints: MediaStreamConstraints = {
      audio: {
        deviceId: deviceId ? { exact: deviceId } : undefined,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        sampleRate: 16000,  // Whisper prefers 16kHz
        channelCount: 1      // Mono audio
      }
    };

    this.mediaStream = await navigator.mediaDevices.getUserMedia(constraints);

    // Set up audio context for visualization/processing
    this.audioContext = new AudioContext({ sampleRate: 16000 });
    const source = this.audioContext.createMediaStreamSource(this.mediaStream);
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 2048;
    source.connect(this.analyser);

    // MediaRecorder for encoding
    const options = {
      mimeType: 'audio/webm;codecs=opus',  // Best browser support
      audioBitsPerSecond: 128000
    };

    this.mediaRecorder = new MediaRecorder(this.mediaStream, options);
  }

  /**
   * Get audio level for visualization (0-100)
   */
  getAudioLevel(): number {
    if (!this.analyser) return 0;

    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(dataArray);

    const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
    return Math.min(100, (average / 255) * 100);
  }

  /**
   * Set callback for audio data chunks
   */
  onDataAvailable(callback: (blob: Blob) => void): void {
    if (!this.mediaRecorder) throw new Error('Not started');

    this.mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        callback(event.data);
      }
    };
  }

  /**
   * Start recording with chunks every N ms
   */
  startRecording(chunkInterval: number = 2000): void {
    if (!this.mediaRecorder) throw new Error('Not started');
    this.mediaRecorder.start(chunkInterval);  // 2-second chunks
  }

  /**
   * Stop recording and cleanup
   */
  stop(): void {
    this.mediaRecorder?.stop();
    this.mediaStream?.getTracks().forEach(track => track.stop());
    this.audioContext?.close();
  }

  /**
   * List available microphone devices
   */
  static async getDevices(): Promise<MediaDeviceInfo[]> {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter(d => d.kind === 'audioinput');
  }
}
```

**File**: `frontend/src/lib/audio-web/types.ts` (NEW)

```typescript
export interface AudioChunk {
  blob: Blob;
  timestamp: number;
  size: number;
}

export interface TranscriptEvent {
  text: string;
  timestamp: string;
  confidence?: number;
}
```

**2. Create Test Page** (isolated testing)

**File**: `frontend/src/app/test-audio/page.tsx` (NEW)

```typescript
'use client';

import { useState } from 'react';
import { WebAudioCapture } from '@/lib/audio-web/capture';

export default function TestAudioPage() {
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [capture, setCapture] = useState<WebAudioCapture | null>(null);
  const [chunks, setChunks] = useState<number>(0);

  const handleStart = async () => {
    try {
      const audioCapture = new WebAudioCapture();
      await audioCapture.start();
      console.log('✅ Browser audio capture started');

      // Monitor audio levels
      const levelInterval = setInterval(() => {
        const level = audioCapture.getAudioLevel();
        setAudioLevel(level);
      }, 100);

      // Log received chunks
      let chunkCount = 0;
      audioCapture.onDataAvailable((blob) => {
        chunkCount++;
        setChunks(chunkCount);
        console.log(`📦 Chunk ${chunkCount}: ${blob.size} bytes`);
      });

      audioCapture.startRecording(2000);  // 2-second chunks
      setCapture(audioCapture);
      setIsRecording(true);

    } catch (error) {
      console.error('❌ Failed to start:', error);
      alert('Microphone access denied or not available');
    }
  };

  const handleStop = () => {
    capture?.stop();
    setIsRecording(false);
    setAudioLevel(0);
  };

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-4">Browser Audio Test</h1>

      <div className="mb-4">
        {!isRecording ? (
          <button
            onClick={handleStart}
            className="bg-blue-500 text-white px-4 py-2 rounded"
          >
            Test Browser Audio
          </button>
        ) : (
          <button
            onClick={handleStop}
            className="bg-red-500 text-white px-4 py-2 rounded"
          >
            Stop Test
          </button>
        )}
      </div>

      <div className="space-y-2">
        <p>Audio Level: {audioLevel.toFixed(0)}%</p>
        <div className="w-full bg-gray-200 h-4 rounded">
          <div
            className="bg-green-500 h-4 rounded transition-all"
            style={{ width: `${audioLevel}%` }}
          />
        </div>
        <p>Chunks Captured: {chunks}</p>
      </div>

      <div className="mt-4 p-4 bg-gray-100 rounded">
        <p className="font-mono text-sm">
          📍 Check browser console for detailed logs<br/>
          ✅ Expected: Mic permission → Audio level bars → Chunks every 2s<br/>
          ⚠️ Main app still uses Tauri (unchanged)
        </p>
      </div>
    </div>
  );
}
```

#### Testing & Verification:

1. Navigate to `http://localhost:3118/test-audio`
2. Click "Test Browser Audio"
3. Grant microphone permission
4. **Expected Results**:
   - ✅ Audio level bars animate with sound
   - ✅ Console shows chunks every 2 seconds
   - ✅ Chunk size is > 0 bytes
5. **Main app at `/`**: Still uses Tauri, works normally

#### End of Day 1 Status:
- ✅ Browser audio capture working independently
- ✅ Tested in isolation
- ✅ Main app unchanged (safe rollback)

---

### Day 2: Add Backend WebSocket (Tauri Still Works) 🔌

**Status**: Main app still uses Tauri (works normally)
**Objective**: Backend can receive browser audio via WebSocket

#### Tasks:

**1. Add WebSocket Endpoint to Backend**

**File**: `backend/app/main.py` (ADD endpoint, don't modify existing)

```python
from fastapi import WebSocket, WebSocketDisconnect
import uuid
import tempfile
from pathlib import Path
from datetime import datetime

# ADD this endpoint (append to file)
@app.websocket("/ws/audio")
async def websocket_audio_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for browser audio streaming
    Phase 1: Simple echo to test connectivity
    """
    await websocket.accept()
    session_id = str(uuid.uuid4())

    logger.info(f"[WebSocket] New session: {session_id}")

    try:
        chunk_count = 0
        while True:
            # Receive audio chunk from browser
            audio_chunk = await websocket.receive_bytes()
            chunk_count += 1

            logger.info(f"[WebSocket] Session {session_id}: Received chunk {chunk_count} ({len(audio_chunk)} bytes)")

            # For now, just acknowledge receipt (no Whisper yet)
            await websocket.send_json({
                "type": "ack",
                "session_id": session_id,
                "chunk_number": chunk_count,
                "size": len(audio_chunk),
                "timestamp": datetime.utcnow().isoformat()
            })

    except WebSocketDisconnect:
        logger.info(f"[WebSocket] Session {session_id} disconnected")
    except Exception as e:
        logger.error(f"[WebSocket] Error in session {session_id}: {str(e)}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
```

**2. Create WebSocket Client**

**File**: `frontend/src/lib/audio-web/websocket-client.ts` (NEW)

```typescript
/**
 * WebSocket client for audio streaming to backend
 */

export type TranscriptCallback = (text: string, timestamp: string) => void;

export class AudioWebSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private transcriptCallback: TranscriptCallback | null = null;

  constructor(url: string) {
    this.url = url;
  }

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('🔌 [WebSocket] Connected to backend');
        resolve();
      };

      this.ws.onerror = (error) => {
        console.error('❌ [WebSocket] Connection error:', error);
        reject(error);
      };

      this.ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('📨 [WebSocket] Received:', data);

        if (data.type === 'ack') {
          console.log(`✅ Chunk ${data.chunk_number} acknowledged (${data.size} bytes)`);
        } else if (data.type === 'transcript' && this.transcriptCallback) {
          this.transcriptCallback(data.text, data.timestamp);
        } else if (data.type === 'error') {
          console.error('❌ Server error:', data.message);
        }
      };

      this.ws.onclose = () => {
        console.log('🔌 [WebSocket] Disconnected');
      };
    });
  }

  sendAudio(blob: Blob): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(blob);
      console.log(`📤 [WebSocket] Sent audio chunk: ${blob.size} bytes`);
    } else {
      console.warn('⚠️ [WebSocket] Not connected, cannot send');
    }
  }

  onTranscript(callback: TranscriptCallback): void {
    this.transcriptCallback = callback;
  }

  disconnect(): void {
    this.ws?.close();
    this.ws = null;
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
```

**3. Update Test Page**

**File**: `frontend/src/app/test-audio/page.tsx` (MODIFY)

```typescript
'use client';

import { useState } from 'react';
import { WebAudioCapture } from '@/lib/audio-web/capture';
import { AudioWebSocket } from '@/lib/audio-web/websocket-client';

export default function TestAudioPage() {
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [capture, setCapture] = useState<WebAudioCapture | null>(null);
  const [ws, setWs] = useState<AudioWebSocket | null>(null);
  const [chunks, setChunks] = useState<number>(0);
  const [wsStatus, setWsStatus] = useState<string>('Not connected');

  const handleStart = async () => {
    try {
      // Step 1: Start browser audio
      const audioCapture = new WebAudioCapture();
      await audioCapture.start();
      console.log('✅ Browser audio started');

      // Step 2: Connect WebSocket
      const websocket = new AudioWebSocket('ws://localhost:5167/ws/audio');
      await websocket.connect();
      setWsStatus('Connected');
      console.log('✅ WebSocket connected');

      // Step 3: Stream audio to WebSocket
      let chunkCount = 0;
      audioCapture.onDataAvailable((blob) => {
        chunkCount++;
        setChunks(chunkCount);
        websocket.sendAudio(blob);
      });

      // Step 4: Monitor audio levels
      const levelInterval = setInterval(() => {
        setAudioLevel(audioCapture.getAudioLevel());
      }, 100);

      audioCapture.startRecording(2000);
      setCapture(audioCapture);
      setWs(websocket);
      setIsRecording(true);

    } catch (error) {
      console.error('❌ Failed:', error);
      alert(`Error: ${error.message}`);
      setWsStatus('Failed');
    }
  };

  const handleStop = () => {
    capture?.stop();
    ws?.disconnect();
    setIsRecording(false);
    setAudioLevel(0);
    setWsStatus('Disconnected');
  };

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-4">Browser Audio + WebSocket Test</h1>

      <div className="mb-4">
        {!isRecording ? (
          <button
            onClick={handleStart}
            className="bg-blue-500 text-white px-4 py-2 rounded"
          >
            Test Full Pipeline
          </button>
        ) : (
          <button
            onClick={handleStop}
            className="bg-red-500 text-white px-4 py-2 rounded"
          >
            Stop Test
          </button>
        )}
      </div>

      <div className="space-y-2">
        <p>WebSocket: <span className={wsStatus === 'Connected' ? 'text-green-600' : 'text-red-600'}>{wsStatus}</span></p>
        <p>Audio Level: {audioLevel.toFixed(0)}%</p>
        <div className="w-full bg-gray-200 h-4 rounded">
          <div
            className="bg-green-500 h-4 rounded transition-all"
            style={{ width: `${audioLevel}%` }}
          />
        </div>
        <p>Chunks Sent: {chunks}</p>
      </div>

      <div className="mt-4 p-4 bg-gray-100 rounded">
        <p className="font-mono text-sm">
          📍 Check browser console AND backend logs<br/>
          ✅ Expected: Browser → WebSocket → Backend logs "Received chunk"<br/>
          ⚠️ Main app still uses Tauri (unchanged)
        </p>
      </div>
    </div>
  );
}
```

#### Testing & Verification:

1. **Start backend** (if not running): `docker logs meetily-backend -f`
2. Navigate to `http://localhost:3118/test-audio`
3. Click "Test Full Pipeline"
4. **Expected Results**:
   - ✅ WebSocket status: "Connected"
   - ✅ Chunks sent counter increments every 2s
   - ✅ Backend logs show: `[WebSocket] Received chunk X (Y bytes)`
   - ✅ Browser console shows: `✅ Chunk X acknowledged`

#### End of Day 2 Status:
- ✅ WebSocket endpoint working
- ✅ Browser can send audio to backend
- ✅ Two-way communication verified
- ✅ Main app unchanged (safe rollback)

---

### Day 3: Connect to Whisper (Full Pipeline Test) 🎯

**Status**: Main app still uses Tauri (works normally)
**Objective**: End-to-end working (Browser → WebSocket → Whisper → Browser)

#### Tasks:

**1. Add ffmpeg Conversion + Whisper Integration**

**File**: `backend/app/main.py` (UPDATE WebSocket endpoint)

```python
import asyncio
import aiohttp
import aiofiles

async def convert_webm_to_wav(webm_file: Path) -> Path:
    """
    Convert WebM/Opus to WAV/PCM using ffmpeg
    Whisper requires: 16kHz, mono, PCM
    """
    wav_file = webm_file.with_suffix('.wav')

    cmd = [
        'ffmpeg', '-y',
        '-i', str(webm_file),
        '-ar', '16000',      # 16kHz sample rate
        '-ac', '1',          # Mono
        '-f', 'wav',         # WAV format
        str(wav_file)
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise Exception(f"FFmpeg conversion failed: {stderr.decode()}")

    logger.debug(f"[Audio] Converted {webm_file.name} to WAV")
    return wav_file


async def transcribe_with_whisper(wav_file: Path) -> str:
    """
    Send WAV file to Whisper server via HTTP POST
    """
    whisper_url = "http://localhost:8178/inference"

    async with aiohttp.ClientSession() as session:
        async with aiofiles.open(wav_file, 'rb') as f:
            file_data = await f.read()

        form_data = aiohttp.FormData()
        form_data.add_field('file', file_data, filename='audio.wav', content_type='audio/wav')

        async with session.post(whisper_url, data=form_data) as response:
            if response.status == 200:
                result = await response.json()
                transcript = result.get('text', '').strip()
                logger.info(f"[Whisper] Transcript: {transcript[:100]}...")
                return transcript
            else:
                error_text = await response.text()
                logger.error(f"[Whisper] Error {response.status}: {error_text}")
                return ""


@app.websocket("/ws/audio")
async def websocket_audio_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for browser audio streaming
    Phase 1 Day 3: Full pipeline with Whisper
    """
    await websocket.accept()
    session_id = str(uuid.uuid4())
    temp_audio_file = Path(tempfile.gettempdir()) / f"audio_{session_id}.webm"

    logger.info(f"[WebSocket] New session: {session_id}")

    try:
        async with aiofiles.open(temp_audio_file, 'wb') as audio_file:
            chunk_count = 0

            while True:
                # Receive audio chunk from browser (WebM/Opus)
                audio_chunk = await websocket.receive_bytes()
                chunk_count += 1
                logger.debug(f"[WebSocket] Session {session_id}: Chunk {chunk_count} ({len(audio_chunk)} bytes)")

                # Append to temporary file
                await audio_file.write(audio_chunk)
                await audio_file.flush()

                # Convert WebM → WAV
                try:
                    wav_file = await convert_webm_to_wav(temp_audio_file)

                    # Send to Whisper
                    transcript = await transcribe_with_whisper(wav_file)

                    if transcript:
                        # Send transcript back to browser
                        await websocket.send_json({
                            "type": "transcript",
                            "text": transcript,
                            "timestamp": datetime.utcnow().isoformat(),
                            "chunk_number": chunk_count
                        })
                        logger.info(f"[WebSocket] Sent transcript: {transcript[:50]}...")

                    # Cleanup WAV file
                    wav_file.unlink(missing_ok=True)

                except Exception as e:
                    logger.error(f"[WebSocket] Processing error: {str(e)}", exc_info=True)
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Processing failed: {str(e)}"
                    })

    except WebSocketDisconnect:
        logger.info(f"[WebSocket] Session {session_id} disconnected")
    except Exception as e:
        logger.error(f"[WebSocket] Error in session {session_id}: {str(e)}", exc_info=True)
    finally:
        # Cleanup
        temp_audio_file.unlink(missing_ok=True)
        logger.info(f"[WebSocket] Cleaned up session {session_id}")
```

**2. Update Backend Dependencies**

**File**: `backend/requirements.txt` (ADD if missing)

```
fastapi[websockets]>=0.104.0
aiohttp>=3.9.0
aiofiles>=23.2.0
```

**3. Update Test Page to Show Transcripts**

**File**: `frontend/src/app/test-audio/page.tsx` (MODIFY)

```typescript
// Add state for transcript
const [transcript, setTranscript] = useState<string>('');

// In handleStart, after websocket.connect():
websocket.onTranscript((text, timestamp) => {
  console.log('📝 Transcript received:', text);
  setTranscript(prev => prev + ' ' + text);
});

// Add to JSX:
<div className="mt-4">
  <h2 className="font-bold">Transcript:</h2>
  <p className="p-4 bg-white border rounded">{transcript || '(Speak to see transcript...)'}</p>
</div>
```

#### Testing & Verification:

1. **Ensure ffmpeg is installed**:
   ```bash
   docker exec -it meetily-backend ffmpeg -version
   ```
2. Navigate to `http://localhost:3118/test-audio`
3. Click "Test Full Pipeline"
4. **Speak into microphone**: "Hello, this is a test"
5. **Expected Results**:
   - ✅ Audio level bars animate
   - ✅ After 2-3 seconds: Transcript appears with your words
   - ✅ Backend logs show: "Converted", "Transcript:", "Sent transcript"
   - ✅ Browser console shows: "📝 Transcript received"

#### End of Day 3 Status:
- 🎉 **FULL NEW SYSTEM WORKING END-TO-END**
- ✅ Browser → WebSocket → ffmpeg → Whisper → Browser
- ✅ Proven working independently
- ✅ Main app still uses Tauri (safe to continue or rollback)

**🎯 CONFIDENCE CHECKPOINT**: New system is proven. Safe to proceed with cutover.

---

### Day 4: Switch Main App (Cutover Day) 🔄

**Status**: Switch main app to new system, keep Tauri code as backup
**Objective**: Main recording UI uses web audio instead of Tauri

#### Tasks:

**1. Create Feature Flag for Easy Rollback**

**File**: `frontend/src/lib/audio-web/config.ts` (NEW)

```typescript
/**
 * Feature flag for audio system
 * Set to true to use web audio, false to use Tauri
 */
export const USE_WEB_AUDIO = true;

// Easy rollback: Just change to false and restart
```

**2. Update RecordingControls Component**

**File**: `frontend/src/components/RecordingControls.tsx` (MODIFY)

```typescript
'use client';

// OLD imports (comment out, don't delete yet)
// import { invoke } from '@tauri-apps/api/core';
// import { listen } from '@tauri-apps/api/event';

// NEW imports
import { WebAudioCapture } from '@/lib/audio-web/capture';
import { AudioWebSocket } from '@/lib/audio-web/websocket-client';
import { USE_WEB_AUDIO } from '@/lib/audio-web/config';

export const RecordingControls: React.FC<RecordingControlsProps> = ({
  onTranscriptReceived,
  onRecordingStart,
  onRecordingStop,
  ...props
}) => {
  // NEW state for web audio
  const [audioCapture, setAudioCapture] = useState<WebAudioCapture | null>(null);
  const [ws, setWs] = useState<AudioWebSocket | null>(null);

  const handleStartRecording = async () => {
    if (USE_WEB_AUDIO) {
      // ========== NEW WEB AUDIO SYSTEM ==========
      try {
        console.log('🌐 Starting web audio system...');

        // Start browser audio capture
        const capture = new WebAudioCapture();
        await capture.start();

        // Connect WebSocket
        const websocket = new AudioWebSocket('ws://localhost:5167/ws/audio');
        await websocket.connect();

        // Stream audio chunks
        capture.onDataAvailable((blob) => {
          websocket.sendAudio(blob);
        });

        // Handle transcripts
        websocket.onTranscript((text, timestamp) => {
          onTranscriptReceived({
            text,
            timestamp,
            confidence: 1.0
          });
        });

        // Start recording (2-second chunks)
        capture.startRecording(2000);

        setAudioCapture(capture);
        setWs(websocket);
        onRecordingStart();

      } catch (error) {
        console.error('❌ Web audio failed:', error);
        alert('Failed to start recording. Please check microphone permissions.');
      }
    } else {
      // ========== OLD TAURI SYSTEM (backup) ==========
      // await invoke('start_recording');
      // onRecordingStart();
      console.error('Tauri system disabled. Set USE_WEB_AUDIO=false to re-enable.');
    }
  };

  const handleStopRecording = () => {
    if (USE_WEB_AUDIO) {
      audioCapture?.stop();
      ws?.disconnect();
      onRecordingStop();
    } else {
      // await invoke('stop_recording');
      // onRecordingStop();
    }
  };

  // ... rest of component (pause/resume buttons, UI, etc.)
};
```

**3. Update RecordingStateContext (if used)**

**File**: `frontend/src/contexts/RecordingStateContext.tsx` (MODIFY similarly)

```typescript
// Comment out Tauri event listeners
// Replace with WebSocket state management
// Keep old code commented for easy rollback
```

#### Testing & Verification:

1. **Start main app**: `cd frontend && pnpm run dev`
2. Navigate to main recording page (`/`)
3. Click "Start Recording"
4. **Expected Results**:
   - ✅ Browser mic permission prompt
   - ✅ Audio level visualization works
   - ✅ Transcript appears as you speak
   - ✅ Stop button works
5. **If something breaks**: Set `USE_WEB_AUDIO = false` in config.ts → restart → back to Tauri

#### End of Day 4 Status:
- 🔄 Main app now uses web audio system
- ✅ Tauri code still in repository (easy rollback)
- ✅ Feature flag allows instant switch back

---

### Day 5: Remove Tauri (Safe Now) 🗑️

**Status**: New system confirmed working, safe to clean up
**Objective**: Remove all Tauri code and dependencies

#### Tasks:

**1. Delete Tauri Codebase**

```bash
rm -rf frontend/src-tauri/
rm frontend/src-tauri.conf.json
rm frontend/Cargo.toml
rm frontend/rust-toolchain.toml
```

**2. Update package.json**

**File**: `frontend/package.json` (MODIFY)

```json
{
  "scripts": {
    "dev": "next dev --port 3118",
    "build": "next build",
    "start": "next start",
    // DELETE these:
    // "tauri:dev": "...",
    // "tauri:build": "..."
  },
  "dependencies": {
    // DELETE these:
    // "@tauri-apps/api": "^2.x",
    // "@tauri-apps/cli": "^2.x",
    // "@tauri-apps/plugin-*": "..."
  }
}
```

**3. Update next.config.js**

**File**: `frontend/next.config.js` (MODIFY)

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  // DELETE:
  // output: 'export',  // Tauri required static export

  // RESTORE normal Next.js config
  reactStrictMode: true,
  // ... other normal config
};

export default nextConfig;
```

**4. Clean Install Dependencies**

```bash
cd frontend
rm -rf node_modules package-lock.json pnpm-lock.yaml
pnpm install
```

**5. Remove Tauri Imports from All Files**

```bash
# Find any remaining Tauri imports
cd frontend
grep -r "@tauri-apps/api" src/

# Remove them manually or with:
find src/ -name "*.tsx" -o -name "*.ts" | xargs sed -i '/tauri-apps/d'
```

**6. Remove Feature Flag (No Longer Needed)**

**File**: `frontend/src/lib/audio-web/config.ts` (DELETE)

**Update RecordingControls.tsx**: Remove `if (USE_WEB_AUDIO)` checks, only keep web audio code

#### Testing & Verification:

1. **Restart dev server**: `pnpm run dev`
2. **Check for errors**:
   - ✅ No `window.__TAURI_INTERNALS__` errors
   - ✅ No import errors for `@tauri-apps/*`
3. **Test main app**: Recording works same as Day 4
4. **Test build**: `pnpm run build` succeeds

#### End of Day 5 Status:
- ✅ All Tauri code removed
- ✅ Clean package.json (no Tauri dependencies)
- ✅ App works as pure web application

---

### Day 6-7: Polish & Production Ready ✨

**Objective**: Fix edge cases, improve UX, optimize performance

#### Tasks:

**1. Error Handling & UX Improvements**

**File**: `frontend/src/lib/audio-web/capture.ts` (IMPROVE)

```typescript
export class WebAudioCapture {
  // Add browser compatibility check
  static isSupported(): boolean {
    return !!(
      navigator.mediaDevices &&
      navigator.mediaDevices.getUserMedia &&
      window.MediaRecorder
    );
  }

  // Add better error messages
  async start(deviceId?: string): Promise<void> {
    if (!WebAudioCapture.isSupported()) {
      throw new Error(
        'Your browser does not support audio recording. Please use Chrome 60+, Firefox 55+, or Edge 79+.'
      );
    }

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (error) {
      if (error.name === 'NotAllowedError') {
        throw new Error('Microphone access denied. Please grant permission and try again.');
      } else if (error.name === 'NotFoundError') {
        throw new Error('No microphone found. Please connect a microphone and try again.');
      } else {
        throw new Error(`Failed to access microphone: ${error.message}`);
      }
    }
  }
}
```

**2. WebSocket Reconnection**

**File**: `frontend/src/lib/audio-web/websocket-client.ts` (IMPROVE)

```typescript
export class AudioWebSocket {
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;  // Start at 1 second

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);

      this.ws.onclose = () => {
        console.log('🔌 [WebSocket] Connection closed');

        // Attempt reconnection
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
          const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts);
          console.log(`🔄 Reconnecting in ${delay}ms... (attempt ${this.reconnectAttempts + 1})`);

          setTimeout(() => {
            this.reconnectAttempts++;
            this.connect();
          }, delay);
        } else {
          console.error('❌ Max reconnection attempts reached');
        }
      };

      // Reset on successful connection
      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        console.log('🔌 [WebSocket] Connected');
        resolve();
      };
    });
  }
}
```

**3. Performance Testing**

Test and optimize:
- [ ] Measure ffmpeg conversion time (target: < 200ms per 2s chunk)
- [ ] Test with different chunk sizes (1s, 2s, 3s, 5s)
- [ ] Profile memory usage (ensure no leaks)
- [ ] Test WebSocket with 10+ minute sessions

**4. Browser Compatibility Testing**

Test on:
- [ ] Chrome 60+ (primary)
- [ ] Firefox 55+ (secondary)
- [ ] Edge 79+ (secondary)
- [ ] Safari 14+ (if time permits)

**5. UI/UX Polish**

Add:
- [ ] Connection status indicator ("Connecting...", "Connected", "Reconnecting...")
- [ ] Better error messages ("Microphone access denied", "Connection lost")
- [ ] Loading states during recording start
- [ ] Graceful degradation on unsupported browsers

**6. Documentation Updates**

**File**: `README.md` (UPDATE)

```markdown
# Meeting Co-Pilot

## Quick Start (Web-Based)

### Backend
```bash
cd backend
./run-docker.sh
```

### Frontend
```bash
cd frontend
pnpm install
pnpm run dev
```

Open http://localhost:3118

## Browser Requirements
- Chrome 60+ (recommended)
- Firefox 55+
- Edge 79+
- Safari 14+ (limited support)

## How It Works
1. Click "Start Recording"
2. Grant microphone permission
3. Speak - transcript appears in real-time
4. Click "Stop Recording" when done
```

#### End of Day 6-7 Status:
- ✅ Production-ready error handling
- ✅ Reconnection logic tested
- ✅ Performance optimized
- ✅ Multi-browser tested
- ✅ Documentation updated

---

## Success Criteria Checklist

Phase 1 is **COMPLETE** when:

### ✅ Functional Requirements
- [ ] User can click "Start Recording" and grant mic permission
- [ ] Audio level visualization shows live input
- [ ] Browser sends audio chunks to backend via WebSocket
- [ ] Backend converts WebM to WAV successfully
- [ ] Whisper transcribes audio and returns text
- [ ] Transcript appears in UI within 3 seconds of speech
- [ ] User can click "Stop Recording" to end session
- [ ] Recording saves to SQLite database

### ✅ Technical Requirements
- [ ] No Tauri code remains in repository
- [ ] `pnpm run dev` starts Next.js web server successfully
- [ ] No browser console errors (no Tauri warnings)
- [ ] WebSocket connection is stable for 10+ minutes
- [ ] Audio quality is acceptable (no garbled speech)
- [ ] Works on Chrome, Firefox, and Edge

### ✅ Documentation Requirements
- [ ] CLAUDE.md updated with Phase 1 completion
- [ ] README has web-based setup instructions
- [ ] Known issues documented
- [ ] Browser compatibility documented

---

## Critical Risks & Mitigations

### 🚨 Risk 1: Audio Format Incompatibility
**Problem**: Browser outputs WebM/Opus, Whisper needs WAV/PCM
**Impact**: HIGH - Transcription fails completely
**Mitigation**:
- Use ffmpeg in backend (proven solution, tested Day 3)
- Fallback: Adjust Whisper to accept Opus (harder)

### 🚨 Risk 2: Real-Time Performance
**Problem**: ffmpeg conversion adds latency
**Impact**: MEDIUM - Users expect < 3s response
**Mitigation**:
- Profile conversion time on Day 3 (target: < 200ms)
- Use hardware acceleration (`-hwaccel cuda`)
- Increase chunk size to 3s if needed

### 🚨 Risk 3: WebSocket Stability
**Problem**: Connection drops lose audio chunks
**Impact**: MEDIUM - Incomplete transcripts
**Mitigation**:
- Implement reconnection logic (Day 6)
- Buffer chunks locally during disconnect
- Show connection status in UI

### 🚨 Risk 4: Browser Compatibility
**Problem**: Not all browsers support MediaRecorder
**Impact**: LOW - 95% of users on modern browsers
**Mitigation**:
- Check `navigator.mediaDevices` before starting
- Show clear error on unsupported browsers
- Document minimum browser versions

---

## Rollback Plan (If Needed)

**If something goes wrong on Day 4-5**:

1. **Immediate Rollback** (< 5 minutes):
   ```typescript
   // frontend/src/lib/audio-web/config.ts
   export const USE_WEB_AUDIO = false;  // Switch back to Tauri
   ```
   Restart dev server → Back to Tauri

2. **Full Rollback** (if Tauri already deleted):
   ```bash
   git revert <commit-hash-of-tauri-removal>
   pnpm install
   pnpm run tauri:dev
   ```

**When is rollback safe?**
- Before Day 5: Tauri code still exists, instant switch
- After Day 5: Need git revert (still recoverable)

---

## Deliverables

### Code Changes
- [x] Create `frontend/src/lib/audio-web/capture.ts`
- [x] Create `frontend/src/lib/audio-web/websocket-client.ts`
- [x] Create `frontend/src/lib/audio-web/types.ts`
- [x] Create `frontend/src/app/test-audio/page.tsx`
- [x] Add `/ws/audio` endpoint to `backend/app/main.py`
- [x] Add `convert_webm_to_wav()` function
- [x] Add `transcribe_with_whisper()` function
- [x] Update `backend/requirements.txt`
- [ ] Modify `frontend/src/components/RecordingControls.tsx`
- [ ] Update `frontend/package.json`
- [ ] Update `frontend/next.config.js`
- [ ] Delete `frontend/src-tauri/` directory

### Documentation
- [ ] Update README with web-based setup
- [ ] Document browser requirements
- [ ] Add WebSocket API documentation
- [ ] Update CLAUDE.md with Phase 1 completion

### Testing
- [ ] Unit tests for `WebAudioCapture` class
- [ ] Integration tests for WebSocket endpoint
- [ ] Manual testing on Chrome, Firefox, Edge
- [ ] Verify audio quality with Whisper

---

## Dependencies & Prerequisites

### Backend
- Python 3.11+
- FastAPI with WebSocket support
- aiohttp, aiofiles
- **ffmpeg** (critical - must be installed)
- Whisper.cpp server on port 8178

### Frontend
- Node.js 18+
- Modern browser (Chrome 60+, Firefox 55+, Edge 79+)

### System
- Docker (recommended for backend)
- Microphone device

---

## Phase 2 Preview

After Phase 1, Phase 2 will add:
- Multi-user WebSocket rooms (Socket.IO)
- Session management (create, join, leave)
- Participant list and presence
- Shared transcript view
- Database schema for sessions/participants

**Estimated Duration**: 3-4 days

---

**Document Status**: Updated with Incremental Migration Strategy
**Last Updated**: 2025-12-24
**Next Review**: After Phase 1 Day 3 (confidence checkpoint)
