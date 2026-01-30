import re
import json
from typing import Optional, Tuple
from jsonschema import validate, ValidationError

PII_REGEX = r"\b\d{11}\b|\b\d{9}\b"
EMAIL_REGEX = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "system prompt",
    "reveal your instructions",
    "reveal system prompt",
    "pokaż instrukcje",
    "zapomnij instrukcje",
    "pokaż prompt",
    "reveal system prompt",
    "../../",
    "/etc/passwd",
    "api"
]

ANSWER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "interakcja": {"type": "boolean"}
    },
    "required": ["answer", "interakcja"]
}

class SecurityGuard:
    @staticmethod
    def sanitize_input(text: str) -> str:
        cleaned_text = re.sub(PII_REGEX, "[REDACTED]", text)
        cleaned_text = re.sub(EMAIL_REGEX, "[EMAIL_REDACTED]", cleaned_text)
        cleaned_text = cleaned_text.replace("..", "")
        return cleaned_text.strip()

    @staticmethod
    def check_injection(text: str) -> Tuple[bool, str]:
        lower_text = text.lower()
        if re.search(EMAIL_REGEX, lower_text):
            return True, "Zablokowano: Wpisywanie adresów e-mail jest niedozwolone"
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

    @staticmethod
    def is_valid_json(text: str) -> Tuple[bool, Optional[str]]:
        try:
            data = json.loads(text)
            validate(instance=data, schema=ANSWER_JSON_SCHEMA)
            return True, None
        except json.JSONDecodeError as e:
            return False, f"Błąd dekodowania JSON: {str(e)}"
        except ValidationError as e:
            return False, f"Błąd walidacji schematu: {e.message}"
        except Exception as e:
            return False, str(e)
