"""
utils/drive_manager.py
╰──➤ Google Drive manager
    Hail | @Drive |~| @Google Drive
    Handles folder creation, file upload, and connection testing
"""

import os
import logging
from pathlib import Path

log = logging.getLogger("ClaudePleX.Drive")

# Try to import Google API — graceful fallback if not installed
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    log.warning("⚠️ Google API client not installed — Drive features will be limited")

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveManager:
    """
    Manages Google Drive operations for the Sentient Backup System.

    Auth methods (in priority order):
    1. Service account JSON key file  (GOOGLE_SERVICE_ACCOUNT_FILE env var)
    2. Service account JSON content   (GOOGLE_SERVICE_ACCOUNT_JSON env var)
    """

    def __init__(self):
        self._service = None
        self._folder_cache: dict[str, str] = {}

        if GOOGLE_AVAILABLE:
            self._init_service()

    def _init_service(self):
        key_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        key_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

        try:
            if key_file and Path(key_file).exists():
                creds = service_account.Credentials.from_service_account_file(
                    key_file, scopes=SCOPES
                )
            elif key_json:
                import json
                info = json.loads(key_json)
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=SCOPES
                )
            else:
                log.warning("⚠️ No Google credentials found. Set GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON")
                return

            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
            log.info("✅ Google Drive service initialized")

        except Exception as e:
            log.error(f"❌ Drive init failed: {e}")

    def test_connection(self) -> bool:
        """Test if Drive connection is working."""
        if not self._service:
            return False
        try:
            self._service.files().list(pageSize=1, fields="files(id)").execute()
            return True
        except Exception as e:
            log.error(f"Drive connection test failed: {e}")
            return False

    def ensure_folder(self, path: str) -> str:
        """
        Ensure a folder path exists in Drive, creating it if needed.
        Path format: "ParentFolder/ChildFolder"
        Returns the folder ID.
        """
        if not self._service:
            raise RuntimeError("Google Drive not connected")

        if path in self._folder_cache:
            return self._folder_cache[path]

        parts  = path.split("/")
        parent = "root"

        for part in parts:
            folder_id = self._get_or_create_folder(part, parent)
            parent    = folder_id

        self._folder_cache[path] = parent
        return parent

    def _get_or_create_folder(self, name: str, parent_id: str) -> str:
        """Get existing folder by name under parent, or create it."""
        query = (
            f"name='{name}' and "
            f"'{parent_id}' in parents and "
            f"mimeType='application/vnd.google-apps.folder' and "
            f"trashed=false"
        )
        results = self._service.files().list(
            q=query,
            fields="files(id, name)",
            pageSize=1,
        ).execute()

        files = results.get("files", [])
        if files:
            return files[0]["id"]

        # Create it
        meta = {
            "name":     name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents":  [parent_id],
        }
        folder = self._service.files().create(body=meta, fields="id").execute()
        log.info(f"📁 Created Drive folder: {name} ({folder['id']})")
        return folder["id"]

    def upload_file(self, local_path: str, filename: str, folder_id: str) -> str:
        """
        Upload a file to Google Drive.
        Returns the uploaded file's Drive ID.
        """
        if not self._service:
            raise RuntimeError("Google Drive not connected")

        meta  = {"name": filename, "parents": [folder_id]}
        media = MediaFileUpload(local_path, resumable=True)

        file = self._service.files().create(
            body=meta,
            media_body=media,
            fields="id, webViewLink",
        ).execute()

        log.info(f"☁️  Uploaded {filename} → Drive ({file['id']})")
        return file["id"]

    def list_folder(self, folder_id: str) -> list[dict]:
        """List files in a Drive folder."""
        if not self._service:
            return []

        results = self._service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id, name, createdTime, size)",
            orderBy="createdTime desc",
            pageSize=50,
        ).execute()

        return results.get("files", [])
