import os
from pathlib import Path
from dotenv import load_dotenv

# Look for .env in multiple locations — works regardless of where package is installed
_ENV_LOCATIONS = [
    Path.home() / ".managebac_mcp" / ".env",   # preferred: ~/.managebac_mcp/.env
    Path(__file__).parent.parent / ".env",       # project root (dev mode)
]
for _env_path in _ENV_LOCATIONS:
    if _env_path.exists():
        load_dotenv(_env_path)
        break
else:
    load_dotenv()  # fallback: let dotenv search upward from CWD

BASE_URL = os.environ.get("MANAGEBAC_URL", "https://es.managebac.com")
EMAIL = os.environ.get("MANAGEBAC_EMAIL", "")
PASSWORD = os.environ.get("MANAGEBAC_PASSWORD", "")

SESSION_FILE = Path.home() / ".managebac_mcp" / "session.json"
CACHE_DB = Path.home() / ".managebac_mcp" / "cache.db"

# Ensure the config directory exists
(Path.home() / ".managebac_mcp").mkdir(exist_ok=True)
