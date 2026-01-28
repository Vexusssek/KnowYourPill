import re
from typing import Optional, Tuple

PII_REGEX = r"\b\d{11}\b|\b\d{9}\b"
INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "system prompt",
    "reveal your instructions",
    "zapomnij instrukcje",
    "pokaż prompt",
    "../../",
    "/etc/passwd"
]

class SecurityGuard:
    @staticmethod
    def sanitize_input(text: str) -> str:
        cleaned_text = re.sub(PII_REGEX, "[REDACTED]", text)
        cleaned_text = cleaned_text.replace("..", "")
        return cleaned_text.strip()

    @staticmethod
    def check_injection(text: str) -> Tuple[bool, str]:
        lower_text = text.lower()
        for keyword in INJECTION_KEYWORDS:
            if keyword in lower_text:
                return True, f"Zablokowano: Wykryto próbę ataku '{keyword}'"
        return False, "OK"

    @staticmethod
    def validate_output(response_text: str) -> str:
        disclaimer = "\n\nUWAGA: System KnowYourPill to asystent pomocniczy. Zawsze skonsultuj się z lekarzem."
        if "UWAGA:" not in response_text:
            return response_text + disclaimer
        return response_text
