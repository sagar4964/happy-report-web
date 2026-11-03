"""Talks to the OpenAI API from the SERVER only. The key never reaches the browser."""
import logging
import os
import time
import requests
from .base import AIError, AIResult

log = logging.getLogger(__name__)


class OpenAIProvider:
    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.model = os.environ.get("OPENAI_MODEL", "").strip()
        try:
            self.timeout = int(os.environ.get("AI_TIMEOUT_SECONDS", "180"))
        except ValueError:
            self.timeout = 180
        if not self.api_key or not self.model:
            raise AIError("The AI connection is not set up yet. An administrator must add "
                          "OPENAI_API_KEY and OPENAI_MODEL to the server settings (.env file).",
                          "config")

    def generate(self, system_prompt, user_message):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        resp = None
        for attempt in range(3):
            try:
                resp = requests.post(self.URL, headers=headers, json=payload, timeout=self.timeout)
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
                time.sleep(2 * (attempt + 1))
                continue
            raise self._error_for(resp.status_code)

        try:
            data = resp.json()
            choice = data["choices"][0]
            text = (choice["message"]["content"] or "").strip()
            finish = choice.get("finish_reason")
            model = data.get("model") or self.model
        except (ValueError, KeyError, IndexError, TypeError):
            raise AIError("The AI sent a reply in an unexpected format. Please try again.", "format")
        if finish == "length":
            raise AIError("The AI's answer was cut off. Please try again.", "truncated")
        if not text:
            raise AIError("The AI sent an empty answer. Please try again.", "empty")
        return AIResult(text=text, model=model)

    @staticmethod
    def _error_for(status):
        log.warning("OpenAI request failed with HTTP status %s", status)
        if status == 401:
            return AIError("The AI service rejected the key. An administrator must check OPENAI_API_KEY.", "auth")
        if status == 403:
            return AIError("The AI service refused access for this key or location.", "auth")
        if status == 404:
            return AIError("The AI model name was not found. An administrator must check OPENAI_MODEL.", "model")
        if status == 429:
            return AIError("The AI service is busy, or the account has no credit left. "
                           "Wait a minute and try again, then check billing.", "rate_limit")
        if status == 400:
            return AIError("The AI service rejected this request (HTTP 400). "
                           "Please tell the administrator.", "bad_request")
        return AIError("The AI service had a problem. Please try again shortly.", "server")
