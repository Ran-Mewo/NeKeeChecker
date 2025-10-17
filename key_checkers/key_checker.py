from abc import ABC, abstractmethod
import random
import re
import os
import json

from fastapi import HTTPException

class KeyChecker(ABC):
    def __init__(self):
        self.keys = {}
        self.compiled_regex = re.compile(self.get_regex_pattern())
        self._load_keys()

    def _store_path(self) -> str:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        storage_dir = os.path.join(base_dir, "storage")
        os.makedirs(storage_dir, exist_ok=True)
        return os.path.join(storage_dir, f"{self.get_name()}.json")

    def _load_keys(self):
        try:
            with open(self._store_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self.keys.update({str(k): str(v) for k, v in data.items()})
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def _save_keys(self):
        try:
            with open(self._store_path(), "w", encoding="utf-8") as f:
                json.dump(self.keys, f, ensure_ascii=False)
        except Exception:
            pass

    @abstractmethod
    def get_regex_pattern(self) -> str:
        pass

    @abstractmethod
    def verify_key(self, key: str):
        pass

    def get_name(self) -> str:
        return self.__class__.__name__.replace("KeyChecker", "").lower()

    def extract_keys(self, text: str) -> list[str]:
        return self.compiled_regex.findall(text)

    def check_text(self, text: str):
        for key in self.extract_keys(text):
            if key not in self.keys:
                self.verify_key(key)

    def list_keys(self, tier=None) -> list[str]:
        return [k for k, v in self.keys.items() if v == tier or (tier is None and v != "dead")]
    
    def list_keys_by_tiers(self) -> dict[str, list[str]]:
        tiers: dict[str, list[str]] = {}
        for key, tier in self.keys.items():
            if tier != "dead": tiers.setdefault(tier, []).append(key)
        return tiers

    def get_key(self, tier=None):
        keys = self.list_keys(tier)
        if not keys:
            raise HTTPException(status_code=404, detail="no keys available for tier")
        return random.choice(keys)


