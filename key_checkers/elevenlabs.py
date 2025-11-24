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


class ElevenLabsKeyChecker(KeyChecker):
    VERIFY_ENDPOINT = "https://api.elevenlabs.io/v1/models"
    PROFILE_ENDPOINT = "https://api.elevenlabs.io/v1/user"

    def get_regex_pattern(self) -> str:
        return r"sk_[a-f0-9]{48}|(?<![A-Za-z0-9])[a-f0-9]{32}(?![A-Za-z0-9])"

    def _fetch_subscription_tier(self, key: str) -> str:
        request = urllib.request.Request(
            self.PROFILE_ENDPOINT,
            headers={
                "xi-api-key": key,
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8")).get("subscription").get("tier")
        except Exception as e:
            print("Error fetching subscription tier for key", key, e)
            return "unknown"

    def verify_key(self, key: str):
        if key in self.invalid_keys:
            return

        request = urllib.request.Request(
            self.VERIFY_ENDPOINT,
            headers={
                "xi-api-key": key,
                "Accept": "application/json",
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                if resp.status >= 400:
                    raise urllib.error.HTTPError(resp.url, resp.status, resp.reason, resp.headers, resp.read())
                tier = self._fetch_subscription_tier(key)
                self.keys[key] = tier
                print("Verified key", key, "with tier", tier)
                self._save_keys()
                return True
        except urllib.error.HTTPError as err:
            if err.code == 429:
                error_message = self._extract_error_message(err).lower()
                print("Error message:", error_message)
                if "quota" in error_message:
                    print("Monthly usage reached for key", key)
                    self.monthly_usage_reached_keys.add(key)
                elif "rate" or "large" in error_message:
                    print("Rate limit reached for key", key, "- retrying in 10 minutes")
                    self.keys[key] = "rate_limited"
                    self._schedule_retry(key)
                    self._save_keys()
                    return

            if key not in self.keys:
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


