"""
BusTrack API Client
Handles auth tokens and HTTP requests with retry logic.
"""

import time
import httpx
from typing import Any, Optional

from config import BASE_URL


class APIClient:
    def __init__(self, base_url: str = BASE_URL, label: str = "client"):
        self.base_url = base_url.rstrip("/")
        self.label = label
        self.token: Optional[str] = None
        self.client = httpx.Client(timeout=15.0)

    def _headers(self):
        h = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _json_headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def login(self, username: str, password: str) -> bool:
        try:
            r = self.client.post(
                f"{self.base_url}/auth/login",
                json={"username": username, "password": password},
            )
            if r.status_code == 200:
                self.token = r.json()["access_token"]
                return True
            print(f"  [{self.label}] Login failed ({r.status_code}): {r.text[:120]}")
            return False
        except Exception as e:
            print(f"  [{self.label}] Login error: {e}")
            return False

    def register(self, username: str, email: str, password: str) -> Optional[dict]:
        try:
            r = self.client.post(
                f"{self.base_url}/auth/register",
                json={"username": username, "email": email, "password": password},
            )
            if r.status_code == 200:
                return r.json()
            if "already registered" in r.text.lower():
                return {"already_exists": True, "username": username}
            print(f"  Register error ({r.status_code}): {r.text[:120]}")
            return None
        except Exception as e:
            print(f"  Register error: {e}")
            return None

    def create_admin_user(self, username: str, email: str, password: str, role: str) -> Optional[dict]:
        try:
            r = self.client.post(
                f"{self.base_url}/admin/users/create",
                json={"username": username, "email": email, "password": password, "role": role},
                headers=self._json_headers(),
            )
            if r.status_code == 200:
                return r.json()
            if "already registered" in r.text.lower():
                return {"already_exists": True, "username": username}
            print(f"  Create user error ({r.status_code}): {r.text[:120]}")
            return None
        except Exception as e:
            print(f"  Create user error: {e}")
            return None

    def post(self, path: str, data: dict, retries: int = 2) -> Optional[dict]:
        for attempt in range(retries + 1):
            try:
                r = self.client.post(
                    f"{self.base_url}{path}",
                    json=data,
                    headers=self._json_headers(),
                )
                if r.status_code in (200, 201):
                    return r.json()
                if attempt < retries:
                    time.sleep(0.5)
                    continue
                print(f"  POST {path} failed ({r.status_code}): {r.text[:120]}")
                return None
            except Exception as e:
                if attempt < retries:
                    time.sleep(1)
                    continue
                print(f"  POST {path} error: {e}")
                return None

    def post_status(self, path: str, data: dict) -> tuple[int, Any]:
        """POST once; return (status_code, parsed JSON or None)."""
        try:
            r = self.client.post(
                f"{self.base_url}{path}",
                json=data,
                headers=self._json_headers(),
            )
            try:
                body = r.json()
            except Exception:
                body = None
            return r.status_code, body
        except Exception as e:
            print(f"  POST {path} error: {e}")
            return 0, None

    def get(self, path: str) -> Any | None:
        try:
            r = self.client.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
            )
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            print(f"  GET {path} error: {e}")
            return None

    def put(self, path: str, data: dict) -> Optional[dict]:
        try:
            r = self.client.put(
                f"{self.base_url}{path}",
                json=data,
                headers=self._json_headers(),
            )
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            print(f"  PUT {path} error: {e}")
            return None

    def post_multipart(self, path: str, form_data: dict, files: dict, retries: int = 2) -> Optional[dict]:
        """
        POST with multipart form data and file uploads.

        Args:
            path: API endpoint path
            form_data: dict of form fields
            files: dict of {field_name: (filename, file_bytes, content_type)}

        Returns:
            Parsed JSON response or None
        """
        for attempt in range(retries + 1):
            try:
                # Prepare files in httpx multipart format
                multipart_files = {}
                for field, (filename, content, content_type) in files.items():
                    multipart_files[field] = (filename, content, content_type)

                # Do NOT set Content-Type header — httpx sets it automatically
                # with the correct multipart boundary
                headers = {}
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"

                r = self.client.post(
                    f"{self.base_url}{path}",
                    data=form_data,
                    files=multipart_files,
                    headers=headers,
                    timeout=30.0,  # Longer timeout for image uploads
                )
                if r.status_code in (200, 201):
                    return r.json()
                if attempt < retries:
                    time.sleep(0.5)
                    continue
                print(f"  POST {path} failed ({r.status_code}): {r.text[:120]}")
                return None
            except Exception as e:
                if attempt < retries:
                    time.sleep(1)
                    continue
                print(f"  POST {path} error: {e}")
                return None

    def close(self):
        self.client.close()
