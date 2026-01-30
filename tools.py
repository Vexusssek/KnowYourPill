import requests
import json
import os
import re
from difflib import SequenceMatcher
from pydantic import BaseModel, Field, ValidationError
from func_timeout import func_timeout, FunctionTimedOut
from typing import Dict, Any, Type, List, Optional
import logging
from google import genai
from google.genai import errors
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env.local")
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tools")


def handle_genai_error(e: Exception) -> str:
    if isinstance(e, errors.APIError):
        if e.status == "RESOURCE_EXHAUSTED":
            return "Przekroczono limit zapytań do serwera. Spróbuj ponownie później."
        if e.status == "NOT_FOUND":
            return "Model nie został odnaleziony."
        if e.status == "PERMISSION_DENIED":
            return "Błąd uprawnień API. Sprawdź klucz API."
        if e.status == "UNAUTHENTICATED":
            return "Błąd autoryzacji. Nieprawidłowy klucz API."
        return f"Błąd serwera AI ({e.status})."
    return f"Wystąpił błąd: {str(e)}"


def get_drug_description(substance: str, mode: str = "groq") -> str:
    actual_mode = "groq" if mode == "local" else mode
    
    api_key = os.getenv("GROQ_API_KEY") if actual_mode == "groq" else os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Brak opisu (brak klucza API)."

    prompt = f"Podaj krótki (2-3 zdania), profesjonalny opis leku/substancji czynnej: {substance}. Skup się na głównym zastosowaniu i mechanizmie działania. Nie używaj formatowania Markdown (pogrubień, list), napisz czysty tekst."

    try:
        if actual_mode == "groq":
            from groq import Groq
            client = Groq(api_key=api_key)
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=256,
            )
            return completion.choices[0].message.content.strip()
        else:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )
            return response.text.strip()
    except Exception as e:
        logger.error(f"Błąd {actual_mode} przy generowaniu opisu: {e}")
        if actual_mode == "groq" and mode == "local":
            logger.info("Próba fallback na Gemini dla opisu...")
            return get_drug_description(substance, mode="gemini")
            
        if actual_mode == "gemini":
            return handle_genai_error(e)
        return "Nie udało się wygenerować opisu."


class IdentifyDrugArgs(BaseModel):
    drug_name: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-zA-Z0-9\s\-\.\u00c0-\u017f]+$")
    drug_dose: Optional[str] = Field(None, max_length=50)
    mode: str = "groq"


def identify_drugs_impl(drug_name: str, drug_dose: Optional[str] = None, mode: str = "groq") -> str:
    url = "https://rejestry.ezdrowie.gov.pl/api/rpl/medicinal-products/search/public"
    

    scored_results = []
    target_name_lower = drug_name.lower()
    
    params = {"name": drug_name, "page": 0, "size": 25}
        
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        results = data.get('content', []) if isinstance(data, dict) else []

        if not results:
            params = {"commonName": drug_name, "page": 0, "size": 25}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            results = data.get('content', []) if isinstance(data, dict) else []

        if not results:
            if not results and len(drug_name) >= 4:
                search_term = drug_name[:-1] if len(drug_name) > 4 else drug_name
                params["name"] = search_term
                response = requests.get(url, params=params, timeout=5)
                data = response.json()
                results = data.get('content', []) if isinstance(data, dict) else []

                if not results and len(drug_name) >= 3:
                    params["name"] = drug_name[:3]
                    response = requests.get(url, params=params, timeout=5)
                    data = response.json()
                    results = data.get('content', []) if isinstance(data, dict) else []

        if not results:
            return json.dumps({"error": f"Nie znaleziono leku '{drug_name}' w oficjalnym rejestrze."})

        target_dose_lower = drug_dose.lower().replace(" ", "") if drug_dose else ""
        target_dose_simple = target_dose_lower.replace("mg", "").replace("ml", "").replace("g", "").replace("µg", "").replace(",", ".")

        for res in results:
            score = 0
            res_name = res.get('medicinalProductName', '').lower()
            res_substance = res.get('commonName', '').lower()
            res_power = res.get('medicinalProductPower', '').lower()
            res_power_normalized = res_power.replace(" ", "")
            res_power_simple = res_power_normalized.replace("mg", "").replace("ml", "").replace("g", "").replace("µg", "").replace(",", ".")

            similarity = SequenceMatcher(None, target_name_lower, res_name).ratio()
            
            if target_name_lower == res_name:
                score += 300
            elif res_name.startswith(target_name_lower + " "):
                score += 250
            elif similarity > 0.9:
                score += int(similarity * 250)
            elif target_name_lower in res_name:
                if re.search(r'\b' + re.escape(target_name_lower) + r'\b', res_name):
                    score += 200
                else:
                    score += 100
            elif similarity > 0.7:
                score += int(similarity * 150)


            substance_similarity = SequenceMatcher(None, target_name_lower, res_substance).ratio()
            if target_name_lower == res_substance:
                score += 150
            elif substance_similarity > 0.8:
                score += int(substance_similarity * 80)
            elif target_name_lower in res_substance or res_substance in target_name_lower:
                score += 60


            if "+" not in target_name_lower and "+" not in target_dose_lower:
                if "+" not in res_substance and "+" not in res_power:
                    score += 50


            if target_dose_lower:

                target_numbers = re.findall(r'\d+[.,]?\d*', target_dose_simple)
                res_numbers = re.findall(r'\d+[.,]?\d*', res_power_simple)


                if target_numbers:
                    match_count = 0
                    temp_res_numbers = [float(n.replace(",", ".")) for n in res_numbers]
                    for tn in target_numbers:
                        tn_normalized = tn.replace(",", ".")
                        tn_f = float(tn_normalized)
                        for i, rn_f in enumerate(temp_res_numbers):

                            if abs(tn_f - rn_f) < 0.01:
                                match_count += 1
                                temp_res_numbers.pop(i)
                                break


                    if match_count == len(target_numbers) and len(target_numbers) == len(res_numbers):
                        score += 200
                    elif match_count > 0:
                        score += 40 * match_count


                if target_dose_lower in res_power_normalized or target_dose_simple in res_power_simple:
                    score += 80

            scored_results.append((score, res))


        scored_results.sort(key=lambda x: x[0], reverse=True)
        best_match = scored_results[0][1]

        name = best_match.get('medicinalProductName', best_match.get('name', 'N/A'))
        substance = best_match.get('commonName', best_match.get('activeSubstanceName', 'Nieznana substancja'))
        power = best_match.get('medicinalProductPower', best_match.get('dose', ''))
        form = best_match.get('pharmaceuticalFormName', '')
        atc = best_match.get('atcCode', '')

        indications = get_drug_description(substance, mode=mode)

        result_data = {
            "name": name,
            "substance": substance,
            "power": power,
            "form": form,
            "atc": atc,
            "indications": indications
        }

        return "Dane z Rejestru: " + json.dumps(result_data, ensure_ascii=False)

    except requests.exceptions.RequestException as e:
        logger.error(f"Błąd sieci: {e}")
        return json.dumps({"error": f"Błąd połączenia z rejestrem: {str(e)}"})
    except Exception as e:
        logger.error(f"Nieoczekiwany błąd: {e}")
        return json.dumps({"error": f"Błąd: {str(e)}"})


class ToolRegistry:
    MAX_RESPONSE_CHARS = 2000

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
            
            if isinstance(result, str) and len(result) > self.MAX_RESPONSE_CHARS:
                logger.warning(f"Przycięto wynik narzędzia {tool_name} z {len(result)} do {self.MAX_RESPONSE_CHARS} znaków.")
                return result[:self.MAX_RESPONSE_CHARS] + "... [Wynik przycięty]"
                
            return result
        except FunctionTimedOut:
            logger.error(f"Timeout narzędzia {tool_name}")
            return "Błąd: Przekroczono czas oczekiwania."
        except Exception as e:
            logger.error(f"Błąd wykonania: {e}")
            return f"Błąd: {str(e)}"


registry = ToolRegistry()
