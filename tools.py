import requests
from pydantic import BaseModel, Field, ValidationError
from func_timeout import func_timeout, FunctionTimedOut
from typing import Dict, Any, Type
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tools")


class IdentifyDrugArgs(BaseModel):
    drug_name: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-zA-Z0-9\s\-\.\u00c0-\u017f]+$")


def identify_drugs_impl(drug_name: str) -> str:
    url = "https://rejestry.ezdrowie.gov.pl/api/rpl/medicinal-products/search/public"
    params = {"name": drug_name, "page": 0, "size": 5}

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        results = data.get('content', []) if isinstance(data, dict) else []

        if not results:
            return f"Nie znaleziono leku '{drug_name}' w oficjalnym rejestrze."

        first_match = results[0]
        name = first_match.get('medicinalProductName', first_match.get('name', 'N/A'))
        substance = first_match.get('commonName', first_match.get('activeSubstanceName', 'Nieznana substancja'))
        power = first_match.get('medicinalProductPower', first_match.get('dose', ''))
        form = first_match.get('pharmaceuticalFormName', '')
        atc = first_match.get('atcCode', '')

        indications = "Brak informacji o wskazaniach w rejestrze."

        img_query = f"lek {name} {power}".replace(" ", "+")
        img_url = f"https://www.google.com/search?q={img_query}&tbm=isch"

        return f"Dane z Rejestru: Lek: {name}, Substancja czynna: {substance}, Dawka: {power}, Postać: {form}, Kod ATC: {atc}, Wskazania: {indications}, Link do zdjęć: {img_url}"

    except requests.exceptions.RequestException as e:
        logger.error(f"Błąd sieci: {e}")
        return f"Błąd połączenia z rejestrem: {str(e)}"
    except Exception as e:
        logger.error(f"Nieoczekiwany błąd: {e}")
        return f"Błąd: {str(e)}"


class ToolRegistry:
    def __init__(self):
        self._tools = {
            "identify_drugs": {
                "func": identify_drugs_impl,
                "args_model": IdentifyDrugArgs
            }
        }

    def validate_and_execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        if tool_name not in self._tools:
            raise ValueError(f"Narzędzie '{tool_name}' niedozwolone.")

        tool_def = self._tools[tool_name]

        try:
            validated_args = tool_def["args_model"](**arguments)
        except ValidationError as e:
            logger.warning(f"Błąd walidacji: {e}")
            return f"Błąd danych: {e.errors()[0]['msg']}"

        try:
            result = func_timeout(
                5.0,
                tool_def["func"],
                kwargs=validated_args.model_dump()
            )
            return result
        except FunctionTimedOut:
            logger.error(f"Timeout narzędzia {tool_name}")
            return "Błąd: Przekroczono czas oczekiwania."
        except Exception as e:
            logger.error(f"Błąd wykonania: {e}")
            return f"Błąd: {str(e)}"


registry = ToolRegistry()
