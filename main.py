from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import os
import json
import logging
from dotenv import load_dotenv

from guards import SecurityGuard
from tools import registry
from rag import rag_system

load_dotenv(dotenv_path=".env.local")
load_dotenv()

if not os.getenv("HF_TOKEN"):
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["HUGGINGFACE_HUB_VERBOSITY"] = "error"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("api")

app = FastAPI(title="KnowYourPill API")


class QueryRequest(BaseModel):
    query: str
    mode: str = "gemini"
    use_functions: bool = True


class QueryResponse(BaseModel):
    answer: str
    logs: List[str]


def call_llm(prompt: str, context: str, mode: str = "gemini", tools_schema=None):
    if mode == "gemini":
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            return "Błąd: Brak klucza API Gemini."

        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)

            tools = None
            if tools_schema:
                def identify_drugs(drug_name: str) -> str:
                    return registry.validate_and_execute("identify_drugs", {"drug_name": drug_name})

                tools = [identify_drugs]

            model = genai.GenerativeModel('gemini-flash-latest', tools=tools)

            full_prompt = f"""Jesteś asystentem medycznym KnowYourPill. Twoim zadaniem jest analiza bezpieczeństwa leków.
Używaj DOSTARCZONEGO KONTEKSTU i NARZĘDZI.

ZASADY ANALIZY:
1. Jeśli użytkownik pyta o lek, a nie masz o nim informacji w kontekście, użyj narzędzia 'identify_drugs'.
2. Jeśli w kontekście brakuje bezpośredniej informacji o interakcji:
   - Przeanalizuj składniki i mechanizm działania na podstawie dostępnych danych o grupach lekowych.
   - Jeśli leki należą do grup wchodzących w znane interakcje, ostrzeż o ryzyku.
   - Zawsze zalecaj konsultację z lekarzem.

Kontekst:
{context}

Pytanie: {prompt}"""

            chat = model.start_chat(enable_automatic_function_calling=True)
            response = chat.send_message(full_prompt)

            return response.text
        except Exception as e:
            return f"Błąd Gemini: {str(e)}"
    else:
        return "Nieobsługiwany tryb"


def local_llm_stub(query: str, context: str, tool_result: str = "") -> str:
    answer = "### Analiza bezpieczeństwa (Baza lokalna)\n\n"

    if tool_result:
        answer += "#### Informacje o składnikach:\n"
        if "Błąd walidacji" in tool_result:
            answer += f"> {tool_result}\n\n"
        else:
            parts = tool_result.replace("Dane z Rejestru: ", "").split(", ")
            for part in parts:
                if "Link do zdjęć:" in part:
                    url = part.split(": ", 1)[-1]
                    answer += f"- [Zobacz zdjęcia i opakowania]({url})\n"
                else:
                    answer += f"- {part}\n"
            answer += "\n"

    if context:
        answer += "#### Znalezione ostrzeżenia i interakcje:\n"
        warnings = context.split("[Źródło ID:")
        for warn in warnings:
            if warn.strip():
                cleaned_warn = warn.strip()
                if "]" in cleaned_warn:
                    content = cleaned_warn.split("]", 1)[-1].strip()
                    source_id = cleaned_warn.split("]", 1)[0]
                    answer += f"- {content} *(Źródło {source_id})*\n"
                else:
                    answer += f"- {cleaned_warn}\n"
        answer += "\n"
    else:
        answer += "#### Informacja:\n"
        answer += "Brak specyficznych ostrzeżeń w lokalnej bazie danych dla tego zapytania.\n\n"

    answer += "---\n"
    answer += "**UWAGA:** System podaje dane z rejestrów i bazy wiedzy. "
    answer += "Zawsze skonsultuj się z lekarzem przed zmianą dawkowania lub łączeniem leków."

    return answer


@app.post("/ask", response_model=QueryResponse)
async def ask_endpoint(request: QueryRequest):
    logs = []
    query = request.query
    logs.append(f"Zapytanie: {query}")

    clean_query = SecurityGuard.sanitize_input(query)
    is_attack, msg = SecurityGuard.check_injection(clean_query)

    if is_attack:
        logger.warning(f"Zablokowano atak: {msg}")
        raise HTTPException(status_code=400, detail=msg)

    logs.append("Weryfikacja bezpieczeństwa: OK")

    tool_result = ""
    all_tool_results = []
    potential_drugs = []

    if request.mode == "gemini":
        try:
            extraction_prompt = f"""Wypisz TYLKO nazwy leków/substancji czynnych występujące w poniższym zapytaniu, w mianowniku liczby pojedynczej, oddzielone przecinkami. Jeśli nie ma nazw leków, zwróć puste pole.
Zapytanie: {clean_query}"""

            gemini_key = os.getenv("GEMINI_API_KEY")
            if gemini_key:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                ex_model = genai.GenerativeModel('gemini-flash-latest')
                ex_res = ex_model.generate_content(extraction_prompt)
                llm_extracted = ex_res.text.strip()
                if llm_extracted:
                    llm_extracted = llm_extracted.replace(".", "").replace("\n", ",")
                    potential_drugs = [d.strip() for d in llm_extracted.split(",") if len(d.strip()) >= 3]
                    logs.append(f"Wykryte leki: {potential_drugs}")
        except Exception as e:
            logger.error(f"Błąd ekstrakcji: {e}")

    if not potential_drugs:
        words = clean_query.split()
        for word in words:
            clean_word = word.strip("?,.!")
            if len(clean_word) < 3: continue

            base_word = clean_word
            if clean_word.endswith("em"):
                base_word = clean_word[:-2]
            elif clean_word.endswith("u"):
                base_word = clean_word[:-1]
            elif clean_word.endswith("a"):
                base_word = clean_word[:-1]

            if len(base_word) < 3: base_word = clean_word

            if base_word[0].isupper() or len(base_word) >= 5:
                if base_word.lower() not in ["czy", "mogę", "brać", "jak", "jest", "razem", "podaj", "skład", "leku"]:
                    potential_drugs.append(base_word)

    potential_drugs = list(dict.fromkeys(potential_drugs))

    if request.mode == "gemini" and request.use_functions:
        try:
            if potential_drugs:
                for drug in potential_drugs:
                    res = registry.validate_and_execute("identify_drugs", {"drug_name": drug})

                    if "Wskazania:" in res:
                        indication_prompt = f"Na co stosuje się lek {drug}? Podaj bardzo krótką odpowiedź w języku polskim (maks 10 słów)."

                        provider_key = os.getenv("GEMINI_API_KEY")
                        if provider_key:
                            try:
                                import google.generativeai as genai
                                genai.configure(api_key=provider_key)
                                ind_model = genai.GenerativeModel('gemini-flash-latest')
                                ind_res = ind_model.generate_content(indication_prompt)
                                indication_text = ind_res.text.strip()

                                if indication_text:
                                    import re
                                    res = re.sub(r"Wskazania: [^,]+", f"Wskazania: {indication_text}", res)
                            except Exception as inner_e:
                                logger.error(f"Błąd wzbogacania danych: {inner_e}")

                    all_tool_results.append(res)
                    logs.append(f"Wynik narzędzia ({drug}): {res}")

                    if ("Nie znaleziono" in res or "Błąd" in res) and len(drug) > 4:
                        alt_name = drug[:-1] if drug.endswith('a') else drug
                        if alt_name != drug:
                            res_alt = registry.validate_and_execute("identify_drugs", {"drug_name": alt_name})
                            if "Nie znaleziono" not in res_alt:
                                all_tool_results.append(res_alt)

                tool_result = "\n".join(all_tool_results)
        except Exception as e:
            logs.append(f"Błąd AI: {str(e)}")
            tool_result = "Błąd komunikacji z AI."

    elif request.mode == "local" and request.use_functions:
        if potential_drugs:
            for drug in potential_drugs:
                res = registry.validate_and_execute("identify_drugs", {"drug_name": drug})
                all_tool_results.append(res)
                logs.append(f"Wynik narzędzia ({drug}): {res}")

                if ("Nie znaleziono" in res or "Błąd" in res) and len(drug) > 4:
                    alt_name = drug[:-1] if drug.endswith('a') else drug
                    if alt_name != drug:
                        res_alt = registry.validate_and_execute("identify_drugs", {"drug_name": alt_name})
                        if "Nie znaleziono" not in res_alt:
                            all_tool_results.append(res_alt)

            tool_result = "\n".join(all_tool_results)

    rag_query = clean_query

    if all_tool_results:
        substances_found = []
        for res in all_tool_results:
            if "Substancja czynna:" in res:
                sub_part = res.split("Substancja czynna:")[1].split(",")[0].strip()
                substances_found.append(sub_part)

        rag_query += " " + " ".join(all_tool_results) + " " + " ".join(substances_found)

    rag_context = rag_system.search(rag_query, k=8)
    logs.append(f"Kontekst RAG pobrany.")

    if request.mode == "gemini":
        try:
            final_answer = call_llm(clean_query, f"{rag_context}\nInfo: {tool_result}", mode=request.mode,
                                    tools_schema=True)

            if hasattr(final_answer, 'content') and final_answer.content is not None:
                final_answer = final_answer.content
            elif not isinstance(final_answer, str):
                final_answer = str(final_answer)

        except Exception as e:
            logger.error(f"Błąd syntezy: {e}")
            final_answer = f"Usługa niedostępna: {str(e)}"
    else:
        final_answer = local_llm_stub(clean_query, rag_context, tool_result)

    final_answer = SecurityGuard.validate_output(final_answer)

    return QueryResponse(answer=final_answer, logs=logs)
