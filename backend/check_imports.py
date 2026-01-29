
import sys
import os

# Add app to path
sys.path.append(os.path.join(os.getcwd(), 'app'))

try:
    print("Checking imports...")
    import uvicorn
    import fastapi
    import httpx
    import aiofiles
    import asyncpg
    from app.audio_recorder import AudioRecorder
    from app.diarization import DiarizationService
    from app.main import app
    print("Imports successful!")
except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
