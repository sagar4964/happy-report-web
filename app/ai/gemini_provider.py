"""Google Gemini connection, used from the SERVER only. The key never reaches the browser.

IMPORTANT: Google's FREE tier may use what you send to improve its products, and people at
Google may read it. Use the free tier with fictional data only.
"""
import logging
import os
import re
import time
import requests
from .base import AIError, AIResult

log = logging.getLogger(__name__)
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
BLOCKED_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "OTHER"}


class GeminiProvider:
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        model = os.environ.get("GEMINI_MODEL", "").strip()
        self.model = model[len("models/"):] if model.startswith("models/") else model
        try:
            self.timeout = int(os.environ.get("AI_TIMEOUT_SECONDS", "180"))
        except ValueError:
            self.timeout = 180
        if not self.api_key or not self.model:
            raise AIError("The AI connection is not set up yet. An administrator must add "
                          "GEMINI_API_KEY and GEMINI_MODEL to the server settings (.env file).",
                          "config")
        if not MODEL_NAME_RE.match(self.model):
            raise AIError("GEMINI_MODEL contains characters that are not allowed. "
                          "Copy the model name exactly, without spaces.", "config")

    def generate(self, system_prompt, user_message):
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        url = self.URL.format(model=self.model)

        resp = None
        for attempt in range(3):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            except requests.Timeout:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise AIError("The AI took too long to answer. Please try again in a minute.", "timeout")
            except requests.ConnectionError:
                raise AIError("Could not reach the AI service. Check the internet connection "
                              "and try again. Your information is saved.", "network")
            except requests.RequestException:
                raise AIError("The AI request failed. Please try again.", "network")

            if resp.status_code == 200:
                break
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            raise self._error_for(resp.status_code)

        try:
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise AIError("The AI did not return an answer. It may have blocked the request. "
                              "Please try again.", "blocked")
            cand = candidates[0]
            finish = cand.get("finishReason")
            parts = (cand.get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts
                           if isinstance(p, dict) and not p.get("thought")).strip()
            model = data.get("modelVersion") or self.model
        except AIError:
            raise
        except (ValueError, AttributeError, TypeError):
            raise AIError("The AI sent a reply in an unexpected format. Please try again.", "format")

        if finish == "MAX_TOKENS":
            raise AIError("The AI's answer was cut off. Please try again.", "truncated")
        if not text:
            if finish in BLOCKED_REASONS:
                raise AIError("The AI declined to answer this request. Please try again, "
                              "or tell the administrator.", "blocked")
            raise AIError("The AI sent an empty answer. Please try again.", "empty")
        return AIResult(text=text, model=model)

    @staticmethod
    def _error_for(status):
        log.warning("Gemini request failed with HTTP status %s", status)
        if status in (401, 403):
            return AIError("The AI service rejected the key. An administrator must check GEMINI_API_KEY.", "auth")
        if status == 404:
            return AIError("The AI model name was not found. An administrator must check GEMINI_MODEL.", "model")
        if status == 429:
            return AIError("The free AI limit has been reached for now. Wait a minute and try again.", "rate_limit")
        if status == 400:
            return AIError("The AI service rejected this request (HTTP 400). Check that GEMINI_API_KEY "
                           "and GEMINI_MODEL are correct.", "bad_request")
        return AIError("The AI service had a problem. Please try again shortly.", "server")
