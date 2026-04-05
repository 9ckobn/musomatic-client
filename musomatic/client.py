"""API client for musomatic server."""

import json
import os
import sys
import time
from pathlib import Path

import httpx

CONFIG_DIR = Path.home() / ".config" / "musomatic"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def ensure_protocol(url: str) -> str:
    if url and not url.startswith("http://") and not url.startswith("https://"):
        return f"http://{url}"
    return url


_cfg = load_config()
API_URL: str = os.getenv("MUSIC_API_URL") or _cfg.get("server_url") or "http://localhost:8844"
API_KEY: str = os.getenv("MUSIC_API_KEY") or _cfg.get("api_key") or ""


def get_headers() -> dict:
    h = {}
    if API_KEY:
        h["x-api-key"] = API_KEY
    return h


class ApiError(Exception):
    """Raised when API returns an error."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def api(method: str, path: str, timeout: float = 120, **kwargs) -> dict:
    try:
        with httpx.Client(base_url=API_URL, timeout=timeout, headers=get_headers()) as c:
            r = getattr(c, method)(path, **kwargs)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise ApiError("Unauthorized — invalid or missing API key. Run: musomatic setup", 401)
        if e.response.status_code == 403:
            raise ApiError("Access denied", 403)
        raise
    except httpx.ConnectError:
        raise ApiError(f"Server unavailable: {API_URL}")
    except httpx.TimeoutException:
        raise ApiError(f"Connection timeout: {API_URL}")


def api_poll(path: str, retries: int = 20) -> dict | None:
    for attempt in range(retries):
        try:
            return api("get", path, timeout=30)
        except ApiError:
            return None
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ReadError,
                httpx.ConnectError, httpx.RemoteProtocolError):
            if attempt < retries - 1:
                time.sleep(3)
            else:
                return None


def cancel_job(job_id: str):
    try:
        api("post", f"/jobs/{job_id}/cancel")
    except Exception:
        pass


def quality_badge(result: dict) -> str:
    if not result:
        return "NOT FOUND"
    bd = result.get("bit_depth", 0)
    sr = result.get("sample_rate", 0)
    src = result.get("source", "")
    rate = f"{sr / 1000:.1f}kHz" if sr else ""
    if bd >= 24:
        return f"Hi-Res {bd}bit/{rate} [{src}]"
    elif bd >= 16:
        return f"CD {bd}bit/{rate} [{src}]"
    return f"{result.get('quality_label', '?')} [{src}]"


def quality_short(bit_depth: int, sample_rate: int) -> str:
    if not bit_depth:
        return "?"
    sr = f"{sample_rate / 1000:.0f}k" if sample_rate else ""
    if bit_depth >= 24:
        return f"24/{sr}"
    return f"16/{sr}"
