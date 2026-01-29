# TEN VAD Integration Plan

## 🛑 Current Status (Jan 2026 Audit)
**Overall Status:** ✅ **COMPLETED**

**Item Status Classification:**
- ✅ **Code Integration:** `StreamingTranscriptionManager` now uses TenVAD as the primary detector (Priority 1).
- ✅ **Fallback Strategy:** Automatically falls back to SileroVAD -> SimpleVAD if TenVAD fails to load.
- ✅ **Optimization:** Thresholds have been tuned (0.5 for Ten/Silero).

**Note:** This document serves as the implementation record for the VAD upgrade.

---

## Objective
Replace the current Silero VAD (Voice Activity Detection) implementation with **TEN VAD** to improve speech detection accuracy, reduce latency, and optimize for real-time conversational AI scenarios.

## Motivation
Recent research and benchmarks indicate that TEN VAD offers several advantages over Silero VAD:
- **Higher Precision:** Better at distinguishing speech from background noise.
- **Lower Latency:** Designed for real-time interactions, enabling faster "barge-in" detection.
- **Lightweight:** Smaller library size and lower memory footprint.
- **Agent-Friendly:** specifically optimized for conversational AI agents.

## Current State
- The project currently utilizes `silero-vad` (likely loaded via `torch.hub` or `onnx`).
- VAD logic is primarily located in `backend/app/vad.py`.
- Dependencies are listed in `backend/requirements.txt`.

## Implementation Plan

### 1. Dependency Management
- Add `ten-vad` (or the specific Python package name, e.g., `ten-ai-vad` or similar, to be confirmed during implementation) to `backend/requirements.txt`.
- Remove `silero` related dependencies if they are no longer needed for other components.

### 2. Code Integration
- **Modify `backend/app/vad.py`**:
    - Import `ten_vad`.
    - Create a new class `TenVAD` that mirrors the interface of `SileroVAD` and `SimpleVAD`.
    - Implement `__init__` to initialize the TEN VAD instance.
    - Implement `is_speech(audio_chunk)` to process audio frames.
    - Implement `get_speech_segments(audio)` (if supported by the library's API or via manual chunking).
    - Ensure `sample_rate` handling (TEN VAD expects 16kHz).

### 3. Testing & Verification
- **Unit Testing**: Create `backend/tests/test_ten_vad.py` (or similar) to verify:
    - Initialization.
    - Speech detection on known samples.
    - Comparison with `SileroVAD` output.
- **Integration**: Update `backend/app/main.py` or configuration to switch the active VAD to `TenVAD`.

## Risks & Mitigations
- **Compatibility**: Ensure TEN VAD supports the specific Python version and OS (Linux/Windows/macOS) used by the project.
- **Fallback**: Keep the Silero VAD code commented out or behind a feature flag initially to allow for easy rollback if TEN VAD proves unstable in this specific environment.

## Next Steps
1.  Install the library.
2.  Create a prototype script.
3.  Integrate into the main codebase.
