import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ENVIO GraphQL
ENVIO_GRAPHQL_URL = os.getenv("ENVIO_GRAPHQL_URL", "")

# Polymarket APIs
GAMMA_API_URL = os.getenv("GAMMA_API_URL", "https://gamma-api.polymarket.com")
DATA_API_URL = os.getenv("DATA_API_URL", "https://data-api.polymarket.com")
CLOB_API_URL = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")

# Settings
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))

# Database
DATABASE_PATH = DATA_DIR / "polybot.db"

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
)
logger = logging.getLogger("polybot")
