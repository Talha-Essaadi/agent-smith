import re
import os
from typing import List
from dotenv import load_dotenv


class KeyManager:
    def __init__(self,
                 env_file: str | None = None,
                 provider_url: str | None = None) -> None:
        if env_file and os.path.exists(env_file):
            load_dotenv(env_file, override=True)
        else:
            load_dotenv()

        self._index = 0
        self.env_vars = os.environ
        self.url = provider_url
        if self.url is None:
            raise ValueError("Provider URL is not set up.")

        self.api_keys = self._get_apis()

    def _local_model(self) -> str | None:
        match = re.search(
            r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?",
            self.url
        )
        if match:
            return "localhost"

        return None

    def _split(self, api_env_values: List[str | None]) -> List[str]:
        cleaned = []
        for value in api_env_values:
            if not value:
                continue
            for key in value.split(","):
                key = key.strip()
                if key and key not in cleaned:
                    cleaned.append(key)
        return cleaned

    def _get_apis(self) -> List[str]:
        if self._local_model() is not None:
            return ["local-key"]

        api_keys = []
        keys = []
        for key in self.env_vars.keys():
            if "api_key" in key.lower():
                keys.append(key)

        api_keys = self._split([self.env_vars.get(key) for key in keys])
        if not api_keys:
            raise ValueError("No API keys are set up.")
        return api_keys

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


if __name__ == "__main__":
    k = KeyManager(".env")
    print(k._get_apis())
