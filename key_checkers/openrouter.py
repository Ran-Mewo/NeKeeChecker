try:
    from .key_checker import KeyChecker
except ImportError:
    import os
    import sys

    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from key_checkers.key_checker import KeyChecker

import json
import urllib.error
import urllib.request


class OpenRouterKeyChecker(KeyChecker):
    KEY_ENDPOINT = "https://openrouter.ai/api/v1/key"
    KEYS_ENDPOINT = "https://openrouter.ai/api/v1/keys"
    CREDITS_ENDPOINT = "https://openrouter.ai/api/v1/credits"

    def get_regex_pattern(self) -> str:
        return r"sk-or-v1-[a-z0-9]{64}"

    def _decode_json(self, payload: bytes) -> dict:
        if not payload:
            return {}
        try:
            return json.loads(payload.decode("utf-8"))
        except Exception:
            return {}

    def _tier_from_payload(self, payload: dict, key: str) -> str:
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(data, dict) and data.get("is_free_tier"):
            return "Free"
        return "Free" if self._remaining_credits(key) <= 0 else "Paid"

    def _remaining_credits(self, key: str) -> float:
        req = urllib.request.Request(
            self.CREDITS_ENDPOINT,
            headers={"Authorization": f"Bearer {key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                if resp.status >= 400:
                    raise urllib.error.HTTPError(resp.url, resp.status, resp.reason, resp.headers, body)
        except urllib.error.HTTPError:
            return float("inf")
        payload = self._decode_json(body)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return float("inf")
        try:
            total_credits = float(data.get("total_credits", 0))
            total_usage = float(data.get("total_usage", 0))
        except (TypeError, ValueError):
            return float("inf")
        return total_credits - total_usage

    def _discover_child_keys(self, key: str):
        req = urllib.request.Request(
            self.KEYS_ENDPOINT,
            headers={"Authorization": f"Bearer {key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                if resp.status >= 400:
                    raise urllib.error.HTTPError(resp.url, resp.status, resp.reason, resp.headers, body)
        except urllib.error.HTTPError:
            return
        payload = self._decode_json(body)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return
        for entry in data:
            if not isinstance(entry, dict) or entry.get("disabled"):
                continue
            hashed_key = entry.get("hash")
            if (
                not isinstance(hashed_key, str)
                or hashed_key == key
                or hashed_key in self.keys
                or hashed_key in self.invalid_keys
            ):
                continue
            self.verify_key(hashed_key)

    def verify_key(self, key: str):
        if key in self.invalid_keys:
            return
        retry = False
        req = urllib.request.Request(
            self.KEY_ENDPOINT,
            headers={"Authorization": f"Bearer {key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                if resp.status >= 400:
                    raise urllib.error.HTTPError(resp.url, resp.status, resp.reason, resp.headers, body)
                tier = self._tier_from_payload(self._decode_json(body), key)
                self.keys[key] = tier
                print("Verified key", key, "with tier", tier)
                self._save_keys()
                self._discover_child_keys(key)
                return True
        except urllib.error.HTTPError as err:
            retry = False
            if err.code == 429:
                error_message = self._extract_error_message(err).lower()
                if "rate" or "large" in error_message:
                    print("Rate limit reached for key", key, "- retrying in 10 minutes")
                    retry = True
                    self._schedule_retry(key)
                if "quota" in error_message:
                    print("Monthly usage reached for key", key)
                    self.monthly_usage_reached_keys.add(key)

            if key not in self.keys and not retry:
                print("Not a valid key", key)
                self.invalid_keys.append(key)
                return
            if self.keys[key] == "dead":
                del self.keys[key]
                print("Deleted key", key, "because it is dead")
            else:
                self.keys[key] = "dead"
                print("Marked key", key, "as dead")
            self._save_keys()