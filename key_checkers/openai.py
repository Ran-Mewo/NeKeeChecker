try:
    from .key_checker import KeyChecker
except ImportError:
    import os, sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from key_checkers.key_checker import KeyChecker
import threading
import urllib.request
import urllib.error
import json

class OpenAIKeyChecker(KeyChecker):
    TIER_BY_LIMITS = { # For gpt-5-nano
        (500, 200_000): "Tier_1",
        (5_000, 2_000_000): "Tier_2",
        (5_000, 4_000_000): "Tier_3",
        (10_000, 10_000_000): "Tier_4",
        (30_000, 180_000_000): "Tier_5",
    }
    def get_regex_pattern(self) -> str:
        return r"sk-[a-zA-Z0-9_-]+T3BlbkFJ[a-zA-Z0-9_-]+"

    def _tier_from_headers(self, headers) -> str:
        rpm = int((headers.get("x-ratelimit-limit-requests") or "0").replace(",", ""))
        tpm = int((headers.get("x-ratelimit-limit-tokens") or "0").replace(",", ""))
        return self.TIER_BY_LIMITS.get((rpm, tpm), "unknown")

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

    def verify_key(self, key: str):
        if key in self.invalid_keys:
            return
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps({"model": "gpt-5-nano", "input": "Just say \"a\"", "reasoning": {"effort": "low"}}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        req_reasoning_summary = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps({"model": "gpt-5-nano", "input": "Just say \"a\"", "reasoning": {"effort": "low", "summary": "auto"}}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status >= 400:
                    raise urllib.error.HTTPError(resp.url, resp.status, resp.reason, resp.headers, resp.read())
                self.keys[key] = self._tier_from_headers(resp.headers)
                print("Verified key", key, "with tier", self.keys[key])
                try:
                    with urllib.request.urlopen(req_reasoning_summary, timeout=10) as resp:
                        if resp.status >= 400:
                            raise urllib.error.HTTPError(resp.url, resp.status, resp.reason, resp.headers, resp.read())
                        print("Key", key, "with tier", self.keys[key], "can do reasoning summary")
                        self.keys_with_special_features.add(key)
                except urllib.error.HTTPError:
                    pass
                self._save_keys()
                return True
        except urllib.error.HTTPError as err:
            if err.code == 429:
                error_message = self._extract_error_message(err).lower()
                if "rate" in error_message:
                    print("Rate limit reached for key", key, "- retrying in 10 minutes")
                    self._schedule_retry(key)
                    return
                if "quota" in error_message:
                    print("Monthly usage reached for key", key)
                    self.monthly_usage_reached_keys.add(key)
                    self._save_keys()
                    return
            if key not in self.keys:
                print("Not a valid key", key)
                self.invalid_keys.append(key)
                return
            if self.keys[key] == "dead":
                del self.keys[key]
                if key in self.keys_with_special_features:
                    self.keys_with_special_features.remove(key)
                print("Deleted key", key, "because it is dead")
            else:
                self.keys[key] = "dead"
                print("Marked key", key, "as dead")
            self._save_keys()

