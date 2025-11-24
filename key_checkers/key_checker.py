from abc import ABC, abstractmethod
import random
import re
import os
import json
import threading
import urllib

from fastapi import HTTPException

class KeyChecker(ABC):
    def __init__(self):
        self.keys = {}
        self.keys_with_special_features = set() # Keys that can do special features like reasoning summary
        self.monthly_usage_reached_keys = set() # Keys that have reached their monthly usage limit
        self.invalid_keys = []
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
                    # Load keys dictionary
                    if "keys" in data:
                        self.keys.update({str(k): str(v) for k, v in data["keys"].items()})
                    else:
                        # Backward compatibility: if no "keys" field, treat whole data as keys
                        self.keys.update({str(k): str(v) for k, v in data.items()})
                    
                    # Load other sets (keys_with_special_features, monthly_usage_reached_keys)
                    if "keys_with_special_features" in data:
                        self.keys_with_special_features = set(data["keys_with_special_features"])
                    if "monthly_usage_reached_keys" in data:
                        self.monthly_usage_reached_keys = set(data["monthly_usage_reached_keys"])
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def _save_keys(self):
        try:
            with open(self._store_path(), "w", encoding="utf-8") as f:
                data = {
                    "keys": self.keys,
                    "keys_with_special_features": list(self.keys_with_special_features),
                    "monthly_usage_reached_keys": list(self.monthly_usage_reached_keys)
                }
                json.dump(data, f, ensure_ascii=False, indent=2)
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
        self.invalid_keys = []

    def list_keys(self, tier=None) -> list[str]:
        return [
            k for k, v in self.keys.items()
            if (
                str(v).lower() != "dead"
                if tier is None
                else str(v).lower() == str(tier).lower()
            )
        ]
    
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
    
    def _schedule_retry(self, key: str, delay_seconds: int = 600) -> None:
        timer = threading.Timer(delay_seconds, self.verify_key, args=(key,))
        timer.daemon = True
        timer.start()

    def _extract_error_message(self, error: urllib.error.HTTPError) -> str:
        try:
            raw_body = error.read()
        except Exception:
            return error.reason or ""
        decoded_body = raw_body.decode("utf-8", errors="ignore") if raw_body else ""
        try:
            payload = json.loads(decoded_body)
            message = payload.get("error", {}).get("message")
            if isinstance(message, str):
                return message
        except (json.JSONDecodeError, AttributeError):
            pass
        return decoded_body or (error.reason or "")


