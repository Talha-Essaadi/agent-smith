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
        self.url = self._get_provider_url(provider_url)
        self.api_keys = self._get_apis()

    def _get_provider_url(self, url: str | None):
        if url is not None:
            return url
        urls = []
        for key in self.env_vars.keys():
            if "provider_url" in key.lower() or "api_url" in key.lower():
                urls.append(key)
        if len(urls) <= 0:
            raise ValueError("No Provider URL exist in .env file."
                             "Make sure you set it before.")
        if len(urls) > 1:
            print("Multi providers URL exist. (Default is the first one)")
        return self.env_vars[urls[0]]

    def _get_provider_name(self) -> List[str]:
        parts: List[str] = []
        match = re.search(
            r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?",
            self.url
        )
        if match:
            return ["localhost"]
        match = re.search(r"https?://([^/]+)", self.url)
        if match:
            domain = match.group(1)
            parts = domain.split(".")

        return [
                p for p in parts
                if p not in ("com", "ai", "api", "generativelanguage", "xyz")
            ]

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
        api_keys = []
        keys = []
        for key in self.env_vars.keys():
            if "api_key" in key.lower():
                keys.append(key)
        provider_names = self._get_provider_name()
        if provider_names == ["localhost"]:
            return ["local-key"]
        keys = sorted(keys)
        for key in keys:
            for name in provider_names:
                if name == "googleapis":
                    if "gemini" in key or "GEMINI" in key:
                        api_keys.append(key)
                        continue
                    if "google" in key or "GOOGLE" in key:
                        api_keys.append(key)
                        continue
                if name.lower() in key or name.upper() in key:
                    api_keys.append(key)

        apis = self._split([self.env_vars.get(api) for api in api_keys])
        if not apis:
            raise ValueError("No API keys are set up.")
        return apis

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
            raise ValueError("No API key are set in the .env file.")
        if response_code == 429:
            self._rotate()
        if response_code in (401, 402, 403):
            self._remove_current_key()
        if not self.api_keys:
            return None
        return self.api_keys[self._index]


if __name__ == "__main__":
    k = KeyManager(".env")
    print(k._get_apis())
