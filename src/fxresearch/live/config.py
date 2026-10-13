from __future__ import annotations

import json
import os
from pathlib import Path

from fxresearch.paths import CONFIG_DIR

LOCAL_CONFIG = CONFIG_DIR / "ctrader_config.json"
EXAMPLE_CONFIG = CONFIG_DIR / "ctrader_config.example.json"

# environment variables win over the local file, so secrets never have to touch disk
ENV_OVERRIDES = {
    "client_id": "CTRADER_CLIENT_ID",
    "client_secret": "CTRADER_CLIENT_SECRET",
    "access_token": "CTRADER_ACCESS_TOKEN",
    "refresh_token": "CTRADER_REFRESH_TOKEN",
    "account_id": "CTRADER_ACCOUNT_ID",
}
PLACEHOLDER_PREFIX = "YOUR_"


class CTraderConfig:

    def __init__(self, path: Path = LOCAL_CONFIG) -> None:
        self.path = path

        self.values: dict = {}
        self.load()

    def load(self) -> None:
        source = self.path if self.path.exists() else EXAMPLE_CONFIG
        self.values = json.loads(source.read_text()) if source.exists() else {}

        for key, env_name in ENV_OVERRIDES.items():
            value = os.environ.get(env_name)
            if value:
                self.values[key] = value

    def get(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def require(self, key: str) -> str:
        value = self.values.get(key)
        if not value or str(value).startswith(PLACEHOLDER_PREFIX):
            raise SystemExit(f"{key} is not set: export {ENV_OVERRIDES.get(key, key.upper())} "
                             f"or fill {self.path.name} (copy it from {EXAMPLE_CONFIG.name})")
        return str(value)

    def save_tokens(self, access_token: str, refresh_token: str) -> None:
        # only the oauth tokens are written, into the git-ignored local file
        stored = json.loads(self.path.read_text()) if self.path.exists() else json.loads(EXAMPLE_CONFIG.read_text())
        stored["access_token"] = access_token
        stored["refresh_token"] = refresh_token
        self.path.write_text(json.dumps(stored, indent=2) + "\n")
        self.values.update(access_token=access_token, refresh_token=refresh_token)

