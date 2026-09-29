"""Launch or reveal the local editor from a desktop shortcut."""
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import webbrowser

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "scripts"))
from animkit import __version__
from animkit.review import review_url

url = "http://127.0.0.1:8766"
try:
    with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
        current = json.load(response)
    if current.get("status") == "READY" and current.get("version") == __version__:
        target = url
        try:
            with urllib.request.urlopen(url + "/api/review", timeout=3) as response:
                active = json.load(response).get("review")
            if active:
                target = review_url(active["request"], url)
        except (OSError, ValueError, KeyError, TypeError):
            # Keep the existing launcher usable while the current request is
            # absent or unavailable; the page displays the underlying state.
            pass
        webbrowser.open(target)
        raise SystemExit(0)
except (OSError, ValueError):
    pass
raise SystemExit(subprocess.call([sys.executable, str(root / "scripts/animation.py"), "editor", "--open"]))
