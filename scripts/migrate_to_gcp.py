"""
Migration Script: Local -> GCP Storage

Scans local recordings directory, merges chunks if needed, and uploads to GCS.
Only runs if STORAGE_TYPE=gcp.
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Add backend to path to import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), "../backend/app"))

try:
    from storage import StorageService, STORAGE_TYPE
    from audio_recorder import AudioRecorder
    import aiofiles
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Make sure you run this script from the project root")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")


async def migrate_meeting(meeting_id: str, local_path: Path):
    """Migrate a single meeting to GCS."""
    logger.info(f"Processing meeting: {meeting_id}")

    merged_wav = local_path / "merged_recording.wav"
    merged_pcm = local_path / "merged_recording.pcm"

    # 1. Check if merged file exists
    source_file = None
    if merged_wav.exists():
        source_file = merged_wav
    elif merged_pcm.exists():
        # Ideally convert PCM to WAV before upload, but for now we upload what we have?
        # Actually AudioRecorder logic prefers WAV in cloud.
        # Let's convert if needed.
        logger.info(f"  Converting PCM to WAV for {meeting_id}")
        async with aiofiles.open(merged_pcm, "rb") as f:
            pcm_data = await f.read()
        wav_data = AudioRecorder.convert_pcm_to_wav(pcm_data)
        async with aiofiles.open(merged_wav, "wb") as f:
            await f.write(wav_data)
        source_file = merged_wav
    else:
        # Try merging chunks
        chunks = list(local_path.glob("chunk_*.pcm"))
        if chunks:
            logger.info(f"  Merging {len(chunks)} chunks for {meeting_id}")
            audio_bytes = await AudioRecorder.merge_chunks(
                meeting_id, str(local_path.parent)
            )
            if audio_bytes:
                wav_data = AudioRecorder.convert_pcm_to_wav(audio_bytes)
                async with aiofiles.open(merged_wav, "wb") as f:
                    await f.write(wav_data)
                source_file = merged_wav
        else:
            logger.warning(f"  No audio found for {meeting_id}, skipping")
            return

    # 2. Upload to GCS
    if source_file and source_file.exists():
        destination = f"{meeting_id}/recording.wav"
        logger.info(f"  Uploading {source_file} -> gs://.../{destination}")

        # We force GCP upload even if env is local? No, script assumes STORAGE_TYPE=gcp set in env
        # Or we can temporarily force it if we import StorageService with GCP config.
        # Ideally user sets env vars before running script.

        success = await StorageService.upload_file(str(source_file), destination)

        if success:
            logger.info(f"✅ Successfully migrated {meeting_id}")
            # Optional: Rename local folder to indicate migrated? Or just leave as cache.
            # (local_path / ".migrated").touch()
        else:
            logger.error(f"❌ Failed to upload {meeting_id}")


async def main():
    if STORAGE_TYPE != "gcp":
        logger.error(
            "STORAGE_TYPE is not 'gcp'. Please set STORAGE_TYPE=gcp in .env before running migration."
        )
        return

    recordings_dir = Path("./backend/data/recordings")
    if not recordings_dir.exists():
        logger.error(f"Recordings directory not found: {recordings_dir}")
        return

    logger.info("Starting migration to Google Cloud Storage...")

    tasks = []
    # Iterate over all meeting directories
    for meeting_dir in recordings_dir.iterdir():
        if meeting_dir.is_dir():
            tasks.append(migrate_meeting(meeting_dir.name, meeting_dir))

    if not tasks:
        logger.info("No meetings found to migrate.")
        return

    # Run migrations (limited concurrency)
    # Process in batches of 5 to avoid network/memory overload
    batch_size = 5
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i : i + batch_size]
        await asyncio.gather(*batch)
        logger.info(
            f"Processed batch {i // batch_size + 1}/{(len(tasks) + batch_size - 1) // batch_size}"
        )

    logger.info("🎉 Migration complete!")


if __name__ == "__main__":
    asyncio.run(main())
