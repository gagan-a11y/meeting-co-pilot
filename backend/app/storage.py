"""
Storage Service Module

Handles file storage operations, abstracting between Local Filesystem and Google Cloud Storage (GCP).
"""

import os
import logging
import shutil
from pathlib import Path
from typing import Optional
from datetime import timedelta

logger = logging.getLogger(__name__)

# Configuration
STORAGE_TYPE = os.getenv("STORAGE_TYPE", "local").lower()  # 'local' or 'gcp'
GCP_BUCKET_NAME = os.getenv("GCP_BUCKET_NAME")
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS", "backend/gcp-service-account.json"
)

# Initialize GCP Client (lazy load)
_gcp_client = None
_gcp_bucket = None


def get_gcp_bucket():
    """Get or initialize the GCP bucket client."""
    global _gcp_client, _gcp_bucket

    if STORAGE_TYPE != "gcp":
        return None

    if _gcp_bucket:
        return _gcp_bucket

    try:
        from google.cloud import storage
        from google.oauth2 import service_account

        if not GCP_BUCKET_NAME:
            logger.error("GCP_BUCKET_NAME environment variable not set")
            return None

        # Authenticate
        if os.path.exists(GOOGLE_CREDENTIALS_PATH):
            credentials = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_PATH
            )
            _gcp_client = storage.Client(credentials=credentials)
        else:
            # Fallback to default credentials (e.g. running on GCE/Cloud Run)
            logger.warning(
                f"Service account key not found at {GOOGLE_CREDENTIALS_PATH}, using default credentials"
            )
            _gcp_client = storage.Client()

        _gcp_bucket = _gcp_client.bucket(GCP_BUCKET_NAME)
        logger.info(f"✅ Connected to GCS bucket: {GCP_BUCKET_NAME}")
        return _gcp_bucket
    except Exception as e:
        logger.error(f"❌ Failed to initialize GCP storage: {e}")
        return None


class StorageService:
    """
    Abstract storage service for meeting recordings.
    """

    @staticmethod
    async def upload_file(local_path: str, destination_path: str) -> bool:
        """
        Upload a file to storage.

        Args:
            local_path: Path to the local file to upload
            destination_path: Logical path in storage (e.g. 'meeting-123/recording.wav')
        """
        if not os.path.exists(local_path):
            logger.error(f"Upload failed: Source file not found {local_path}")
            return False

        if STORAGE_TYPE == "gcp":
            return await StorageService._upload_to_gcp(local_path, destination_path)
        else:
            return await StorageService._save_locally(local_path, destination_path)

    @staticmethod
    async def download_file(source_path: str, local_destination: str) -> bool:
        """
        Download a file from storage to local path.
        """
        if STORAGE_TYPE == "gcp":
            return await StorageService._download_from_gcp(
                source_path, local_destination
            )
        else:
            return await StorageService._copy_locally(source_path, local_destination)

    @staticmethod
    async def delete_file(path: str) -> bool:
        """Delete a file from storage."""
        if STORAGE_TYPE == "gcp":
            return await StorageService._delete_from_gcp(path)
        else:
            return await StorageService._delete_locally(path)

    @staticmethod
    async def generate_signed_url(
        path: str, expiration_seconds: int = 3600
    ) -> Optional[str]:
        """
        Generate a temporary accessible URL for a file.
        For GCP: Generates a Signed URL.
        For Local: Returns a static file path (assuming served via FastAPI StaticFiles).
        """
        if STORAGE_TYPE == "gcp":
            return await StorageService._generate_gcp_signed_url(
                path, expiration_seconds
            )
        else:
            # Local dev mode: Return relative URL to be served by StaticFiles
            # We assume 'data/recordings' is mounted at '/audio'
            # path is like 'meeting-123/recording.wav'
            return f"/audio/{path}"

    @staticmethod
    async def check_file_exists(path: str) -> bool:
        """Check if file exists in storage."""
        if STORAGE_TYPE == "gcp":
            return await StorageService._check_gcp_exists(path)
        else:
            return await StorageService._check_local_exists(path)

    # --- Internal Implementations ---

    @staticmethod
    async def _check_gcp_exists(blob_name: str) -> bool:
        try:
            bucket = get_gcp_bucket()
            if not bucket:
                return False

            blob = bucket.blob(blob_name)

            import asyncio

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, blob.exists)
        except Exception as e:
            logger.error(f"GCS Exists check failed: {e}")
            return False

    @staticmethod
    async def _check_local_exists(relative_path: str) -> bool:
        base_path = Path("./data/recordings")
        return (base_path / relative_path).exists()

    @staticmethod
    async def _upload_to_gcp(local_path: str, blob_name: str) -> bool:
        try:
            bucket = get_gcp_bucket()
            if not bucket:
                return False

            blob = bucket.blob(blob_name)

            # Run blocking I/O in executor
            import asyncio

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, blob.upload_from_filename, local_path)

            logger.info(f"⬆️  Uploaded to GCS: gs://{GCP_BUCKET_NAME}/{blob_name}")
            return True
        except Exception as e:
            logger.error(f"GCS Upload failed: {e}")
            return False

    @staticmethod
    async def _download_from_gcp(blob_name: str, local_path: str) -> bool:
        try:
            bucket = get_gcp_bucket()
            if not bucket:
                return False

            blob = bucket.blob(blob_name)

            # Ensure directory exists
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            # Run blocking I/O in executor
            import asyncio

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, blob.download_to_filename, local_path)

            logger.info(f"⬇️  Downloaded from GCS: {blob_name} -> {local_path}")
            return True
        except Exception as e:
            logger.error(f"GCS Download failed: {e}")
            return False

    @staticmethod
    async def _delete_from_gcp(blob_name: str) -> bool:
        try:
            bucket = get_gcp_bucket()
            if not bucket:
                return False

            blob = bucket.blob(blob_name)

            import asyncio

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, blob.delete)

            logger.info(f"🗑️  Deleted from GCS: {blob_name}")
            return True
        except Exception as e:
            logger.warning(f"GCS Delete failed (might not exist): {e}")
            return False

    @staticmethod
    async def _generate_gcp_signed_url(
        blob_name: str, expiration: int
    ) -> Optional[str]:
        try:
            bucket = get_gcp_bucket()
            if not bucket:
                return None

            blob = bucket.blob(blob_name)

            import asyncio

            loop = asyncio.get_running_loop()

            url = await loop.run_in_executor(
                None,
                lambda: blob.generate_signed_url(
                    version="v4", expiration=timedelta(seconds=expiration), method="GET"
                ),
            )
            return url
        except Exception as e:
            logger.error(f"Signed URL generation failed: {e}")
            return None

    # --- Local Fallbacks ---

    @staticmethod
    async def _save_locally(local_source: str, relative_dest: str) -> bool:
        try:
            # Base storage path
            base_path = Path("./data/recordings")
            dest_path = base_path / relative_dest

            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # If source is same as dest (already in place), do nothing
            if os.path.abspath(local_source) == os.path.abspath(dest_path):
                return True

            shutil.copy2(local_source, dest_path)
            return True
        except Exception as e:
            logger.error(f"Local save failed: {e}")
            return False

    @staticmethod
    async def _copy_locally(relative_source: str, local_dest: str) -> bool:
        try:
            base_path = Path("./data/recordings")
            source_path = base_path / relative_source

            if not source_path.exists():
                return False

            os.makedirs(os.path.dirname(local_dest), exist_ok=True)
            shutil.copy2(source_path, local_dest)
            return True
        except Exception as e:
            logger.error(f"Local copy failed: {e}")
            return False

    @staticmethod
    async def _delete_locally(relative_path: str) -> bool:
        try:
            base_path = Path("./data/recordings")
            target_path = base_path / relative_path

            if target_path.exists():
                os.remove(target_path)
                return True
            return False
        except Exception as e:
            logger.error(f"Local delete failed: {e}")
            return False
