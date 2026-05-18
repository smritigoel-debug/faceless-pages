"""
Google Drive uploader for Faceless Pages generated content.

Usage:
    from drive_uploader import DriveUploader
    uploader = DriveUploader("service_account.json", "FOLDER_ID")
    link = uploader.upload_url("https://...image.png", "cuet_static.png")
"""

import os
import io
import json
import time
import mimetypes
import urllib.request
import urllib.parse
import urllib.error
import base64
import hashlib
import hmac

# ---------------------------------------------------------------------------
# Minimal Google Auth (no external deps beyond requests)
# ---------------------------------------------------------------------------

def _load_sa(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _make_jwt(sa: dict) -> str:
    """Create a signed JWT for service account auth."""
    import time, json, base64

    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
    now = int(time.time())
    claims = {
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/drive.file",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now,
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    signing_input = header + b"." + payload

    # Sign with RSA private key using cryptography lib or fallback to subprocess openssl
    private_key_pem = sa["private_key"].encode()
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        private_key = serialization.load_pem_private_key(private_key_pem, password=None)
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    except ImportError:
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
            f.write(private_key_pem)
            key_file = f.name
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_file],
            input=signing_input,
            capture_output=True,
        )
        os.unlink(key_file)
        signature = result.stdout

    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return (signing_input + b"." + sig_b64).decode()


def _get_access_token(sa_path: str) -> str:
    import requests
    sa = _load_sa(sa_path)
    jwt = _make_jwt(sa)
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Drive Uploader
# ---------------------------------------------------------------------------

class DriveUploader:
    def __init__(self, sa_path: str, folder_id: str):
        self.sa_path = sa_path
        self.folder_id = folder_id
        self._token = None
        self._token_exp = 0

    def _auth_header(self) -> dict:
        import requests
        if time.time() > self._token_exp - 60:
            self._token = _get_access_token(self.sa_path)
            self._token_exp = time.time() + 3500
        return {"Authorization": f"Bearer {self._token}"}

    def upload_bytes(self, data: bytes, filename: str, mime: str = None) -> str:
        """Upload raw bytes to Drive folder. Returns shareable web view link."""
        import requests
        if mime is None:
            mime, _ = mimetypes.guess_type(filename)
            mime = mime or "application/octet-stream"

        headers = self._auth_header()

        # Initiate resumable upload
        meta = {"name": filename, "parents": [self.folder_id]}
        init_resp = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            headers={**headers, "Content-Type": "application/json; charset=UTF-8",
                     "X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(len(data))},
            json=meta,
            timeout=15,
        )
        init_resp.raise_for_status()
        upload_url = init_resp.headers["Location"]

        # Upload data
        up_resp = requests.put(
            upload_url,
            headers={"Content-Type": mime, "Content-Length": str(len(data))},
            data=data,
            timeout=120,
        )
        up_resp.raise_for_status()
        file_id = up_resp.json()["id"]

        # Make publicly readable (anyone with link)
        requests.post(
            f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions",
            headers={**headers, "Content-Type": "application/json"},
            json={"role": "reader", "type": "anyone"},
            timeout=10,
        )

        return f"https://drive.google.com/file/d/{file_id}/view"

    def upload_url(self, url: str, filename: str) -> str:
        """Download content from a URL and upload it to Drive. Returns Drive link."""
        import requests
        print(f"  Downloading {filename} from CDN...")
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        mime = resp.headers.get("Content-Type", "").split(";")[0] or None
        print(f"  Uploading {filename} ({len(resp.content) // 1024}KB) to Drive...")
        link = self.upload_bytes(resp.content, filename, mime)
        print(f"  Done: {link}")
        return link


# ---------------------------------------------------------------------------
# Batch upload from a content_plan results file
# ---------------------------------------------------------------------------

def upload_content_batch(sa_path: str, folder_id: str, results: list[dict]) -> list[dict]:
    """
    Given a list of content dicts (each with generation_job_id + type),
    fetch the Higgsfield CDN URL and upload to Drive.
    Adds 'drive_link' to each dict.
    """
    uploader = DriveUploader(sa_path, folder_id)

    for item in results:
        job_id = item.get("generation_job_id") or item.get("job_result", {}).get("id")
        content_type = item.get("type", "static")
        item_id = item.get("id", "content")
        ext = "mp4" if content_type == "reel" else "png"
        filename = f"{item_id}.{ext}"

        cdn_url = item.get("cdn_url")
        if not cdn_url:
            print(f"  [SKIP] No cdn_url for {item_id}")
            continue

        try:
            link = uploader.upload_url(cdn_url, filename)
            item["drive_link"] = link
        except Exception as e:
            print(f"  [ERROR] {item_id}: {e}")
            item["drive_link"] = None

    return results


if __name__ == "__main__":
    import sys, json

    if len(sys.argv) < 4:
        print("Usage: python drive_uploader.py <service_account.json> <folder_id> <results.json>")
        sys.exit(1)

    sa_path, folder_id, results_file = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(results_file) as f:
        results = json.load(f)

    updated = upload_content_batch(sa_path, folder_id, results)

    out = results_file.replace(".json", "_with_drive.json")
    with open(out, "w") as f:
        json.dump(updated, f, indent=2)

    print(f"\nDone. Drive links saved to {out}")
    for item in updated:
        print(f"  [{item['id']}] {item.get('drive_link', 'NO LINK')}")
