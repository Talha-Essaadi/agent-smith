from collections.abc import Mapping
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from dotenv import dotenv_values


_API_KEY_NAME = re.compile(r"(?:[A-Z0-9_]+_)?API_KEY(?:S|_?\d+)?", re.IGNORECASE)


class KeyManager:
    def __init__(self,
                 env_file: str | None = None,
                 provider_url: str | None = None) -> None:
        if not provider_url:
            raise ValueError("Provider URL is not set up.")
        endpoint = urlsplit(provider_url)
        if endpoint.scheme not in ("http", "https") or not endpoint.hostname:
            raise ValueError("Provider URL must be a valid HTTP or HTTPS URL.")

        self._index = 0
        if endpoint.hostname in ("localhost", "127.0.0.1", "::1"):
            self.api_keys = ["local-key"]
        else:
            self.api_keys = self._get_apis(env_file)

    @staticmethod
    def _read_keys(variables: Mapping[str, str | None]) -> list[str]:
        keys = []
        for name, value in variables.items():
            if not value or not _API_KEY_NAME.fullmatch(name):
                continue
            for key in value.split(","):
                key = key.strip()
                if key and key not in keys:
                    keys.append(key)
        return keys

    def _get_apis(self, env_file: str | None) -> list[str]:
        if env_file is not None:
            path = Path(env_file)
            if not path.is_file():
                raise FileNotFoundError(f"API key file not found: {path}")
            keys = self._read_keys(dotenv_values(path))
        else:
            # Exam scripts export keys before invoking the agent.
            keys = self._read_keys(os.environ) or self._read_keys(dotenv_values())
        if not keys:
            raise ValueError("No API keys are set up for the selected provider.")
        return keys

    def _rotate(self):
        len_keys = len(self.api_keys)
        if len_keys > 0:
            self._index = (self._index + 1) % len_keys
        else:
            self._index = 0

    def _remove_current_key(self):
        del self.api_keys[self._index]
        if len(self.api_keys) <= 0:
            raise ValueError("No API key still works")
        self._index = self._index % len(self.api_keys)

    def get_key(self, response_code: int = 200) -> str | None:
        if not self.api_keys:
            return None
        if response_code == 429:
            self._rotate()
        if response_code in (401, 402, 403):
            self._remove_current_key()
        return self.api_keys[self._index]
