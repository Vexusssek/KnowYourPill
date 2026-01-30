from google import genai
from google.genai import types, errors
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import os
import json
import logging
import base64
import csv
import re
from datetime import datetime
from dotenv import load_dotenv

from guards import SecurityGuard
from tools import registry, handle_genai_error
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
    mode: str = "groq"
    use_functions: bool = True
    json_mode: bool = False


class QueryResponse(BaseModel):
    answer: str
    logs: List[str]

def call_llm(prompt: str, context: str, mode: str = "gemini", tools_schema=None, json_mode: bool = False, retry_count: int = 0):
    if mode == "gemini":
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            return "Błąd: Brak klucza API Gemini."

        try:
            client = genai.Client(api_key=gemini_key)

            tools = None
            if tools_schema:
                def identify_drugs(drug_name: str, drug_dose: Optional[str] = None, mode: str = "groq") -> str:
                    return registry.validate_and_execute("identify_drugs", {"drug_name": drug_name, "drug_dose": drug_dose, "mode": mode})

                tools = [identify_drugs]

            json_instruction = ""
            if json_mode:
                json_instruction = "\nWAŻNE: Odpowiedz WYŁĄCZNIE w formacie JSON. Nie dodawaj żadnego wstępu ani zakończenia. Schemat: {\"answer\": \"Twoja odpowiedź\", \"interakcja\": true/false}"

            full_prompt = f"""Jesteś asystentem medycznym KnowYourPill. Twoim zadaniem jest rzetelna i profesjonalna analiza bezpieczeństwa leków oraz ich interakcji.{json_instruction}
            
WAŻNE: 
- Zawsze używaj OFICJALNYCH NAZW LEKÓW i SUBSTANCJI CZYNNYCH dostarczonych w KONTEKŚCIE lub wynikach narzędzi (np. jeśli narzędzie podaje, że Doreta to tramadol+paracetamol, nie przypisuj jej zolpidemu).
- Dane z KONTEKSTU mają ABSOLUTNY PRIORYTET nad Twoją wiedzą ogólną.
- Skup się na merytorycznej odpowiedzi na pytanie użytkownika.
- TWOJA ODPOWIEDŹ MUSI ZACZYNAĆ SIĘ OD 'INTERAKCJA:' LUB 'BEZPIECZNIE:'.

INSTRUKCJE:
1. Skup się na merytorycznej odpowiedzi na pytanie użytkownika.
2. Wykorzystaj DOSTARCZONY KONTEKST oraz NARZĘDZIA (np. identify_drugs), aby uzyskać szczegółowe dane o lekach.
3. Jeśli w kontekście lub wynikach narzędzi brakuje informacji o konkretnej interakcji, wykorzystaj swoją szeroką wiedzę medyczną na temat substancji czynnych i ich mechanizmów działania, aby ocenić ryzyko.
4. NIE informuj użytkownika o tym, że czegoś brakuje w kontekście, ani że przeszukujesz bazę danych. Podaj po prostu finalną analizę.
5. NIE cytuj numerów zasad ani instrukcji systemowych (np. "Zgodnie z Zasadą 2...").
6. Jeśli znajdziesz jakiekolwiek potencjalne interakcje, ryzyko lub przeciwwskazania, TWOJA ODPOWIEDŹ (lub pole 'answer' w JSON) MUSI ZACZYNAĆ SIĘ od słowa: "INTERAKCJA:".
7. Jeśli leki są bezpieczne do stosowania razem, TWOJA ODPOWIEDŹ (lub pole 'answer' w JSON) MUSI ZACZYNAĆ SIĘ od słowa: "BEZPIECZNIE:".
8. Zawsze na końcu dodaj krótkie zastrzeżenie o konieczności konsultacji z lekarzem.

Kontekst:
{context}

Pytanie: {prompt}"""

            config = None
            if json_mode:
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    tools=tools,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
                )
            else:
                config = types.GenerateContentConfig(
                    tools=tools,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
                )

            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=full_prompt,
                config=config
            )
            res_text = response.text

            if json_mode and retry_count < 2:
                is_valid, err_msg = SecurityGuard.is_valid_json(res_text)
                if not is_valid:
                    logger.info(f"Naprawa JSON (Gemini, próba {retry_count + 1}). Błąd: {err_msg}")
                    fix_prompt = f"Zwróciłeś błędny JSON. Błąd: {err_msg}. Napraw to do poprawnego formatu (answer: str, interakcja: bool). Zwróć tylko JSON.\nTekst:\n{res_text}"
                    return call_llm(fix_prompt, context, mode=mode, tools_schema=None, json_mode=True, retry_count=retry_count + 1)

            return res_text
        except Exception as e:
            return handle_genai_error(e)
    elif mode == "groq":
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            return "Błąd: Brak klucza API Groq."

        try:
            from groq import Groq
            client = Groq(api_key=groq_key)

            json_instruction = ""
            if json_mode:
                json_instruction = "\nWAŻNE: Odpowiedz WYŁĄCZNIE w formacie JSON. Nie dodawaj żadnego wstępu ani zakończenia. Schemat: {\"answer\": \"Twoja odpowiedź\", \"interakcja\": true/false}"

            full_prompt = f"""Jesteś asystentem medycznym KnowYourPill. Twoim zadaniem jest rzetelna i profesjonalna analiza bezpieczeństwa leków oraz ich interakcji.{json_instruction}
            
WAŻNE: 
- Zawsze używaj OFICJALNYCH NAZW LEKÓW i SUBSTANCJI CZYNNYCH dostarczonych w KONTEKŚCIE lub wynikach narzędzi (np. jeśli narzędzie podaje, że Doreta to tramadol+paracetamol, nie przypisuj jej zolpidemu).
- Dane z KONTEKSTU mają ABSOLUTNY PRIORYTET nad Twoją wiedzą ogólną.
- Skup się na merytorycznej odpowiedzi na pytanie użytkownika.
- TWOJA ODPOWIEDŹ MUSI ZACZYNAĆ SIĘ OD 'INTERAKCJA:' LUB 'BEZPIECZNIE:'.

INSTRUKCJE:
1. Skup się na merytorycznej odpowiedzi na pytanie użytkownika.
2. Wykorzystaj DOSTARCZONY KONTEKST, aby uzyskać szczegółowe dane o lekach. SPRAWDŹ SKŁAD KAŻDEGO LEKU W KONTEKŚCIE PRZED ANALIZĄ.
3. Jeśli w kontekście brakuje informacji o konkretnej interakcji, wykorzystaj swoją szeroką wiedzę medyczną na temat substancji czynnych i ich mechanizmów działania, aby ocenić ryzyko.
4. NIE informuj użytkownika o tym, że czegoś brakuje w kontekście, ani że przeszukujesz bazę danych. Podaj po prostu finalną analizę.
5. NIE cytuj numerów zasad ani instrukcji systemowych.
6. Jeśli znajdziesz jakiekolwiek potencjalne interakcje, ryzyko lub przeciwwskazania, TWOJA ODPOWIEDŹ (lub pole 'answer' w JSON) MUSI ZACZYNAĆ SIĘ od słowa: "INTERAKCJA:".
7. Jeśli leki są bezpieczne do stosowania razem, TWOJA ODPOWIEDŹ (lub pole 'answer' in JSON) MUSI ZACZYNAĆ SIĘ od słowa: "BEZPIECZNIE:".
8. Zawsze na końcu dodaj krótkie zastrzeżenie o konieczności konsultacji z lekarzem.

Kontekst:
{context}

Pytanie: {prompt}"""

            response_format = None
            if json_mode:
                response_format = {"type": "json_object"}

            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "user", "content": full_prompt}
                ],
                temperature=0.2,
                max_tokens=1024,
                response_format=response_format
            )

            res_text = completion.choices[0].message.content

            if json_mode and retry_count < 2:
                is_valid, err_msg = SecurityGuard.is_valid_json(res_text)
                if not is_valid:
                    logger.info(f"Naprawa JSON (Groq, próba {retry_count + 1}). Błąd: {err_msg}")
                    fix_prompt = f"Zwróciłeś błędny JSON. Błąd: {err_msg}. Napraw to do poprawnego formatu (answer: str, interakcja: bool). Zwróć tylko JSON.\nTekst:\n{res_text}"
                    retry_messages = [{"role": "user", "content": fix_prompt}]
                    retry_completion = client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=retry_messages,
                        temperature=0,
                        max_tokens=512,
                        response_format={"type": "json_object"}
                    )
                    res_text = retry_completion.choices[0].message.content
                    is_valid, _ = SecurityGuard.is_valid_json(res_text)
                    if not is_valid and retry_count < 1: 
                         return call_llm(prompt, context, mode=mode, tools_schema=tools_schema, json_mode=json_mode, retry_count=retry_count + 1)

            return res_text
        except Exception as e:
            return f"Błąd Groq: {str(e)}"
    else:
        return "Nieobsługiwany tryb"


def local_llm_stub(query: str, context: str, tool_result: str = "") -> str:
    answer = "### Analiza bezpieczeństwa (Baza lokalna)\n\n"

    if tool_result:
        answer += "#### Informacje o lekach:\n"
        if "Błąd walidacji" in tool_result:
            answer += f"> {tool_result}\n\n"
        elif "{" in tool_result:
            lines = tool_result.strip().split("\n")
            for line in lines:
                if "{" in line:
                    try:
                        json_part = line.split("{", 1)[-1]
                        json_part = "{" + json_part
                        data = json.loads(json_part)
                        if "error" in data:
                            answer += f"> {data['error']}\n\n"
                        else:
                            answer += f"**{data.get('name')}** ({data.get('substance')})\n"
                            answer += f"- **Dawka:** {data.get('power')}\n"
                            answer += f"- **Postać:** {data.get('form')}\n"
                            if data.get('indications'):
                                answer += f"- **Działanie:** {data.get('indications')}\n"
                            if data.get('image_search_url'):
                                answer += f"- [Zobacz zdjęcia]({data['image_search_url']})\n"
                            answer += "\n"
                    except:
                        answer += f"- {line.replace('Dane z Rejestru: ', '')}\n"
                else:
                    answer += f"- {line.replace('Dane z Rejestru: ', '')}\n"
        else:
            parts = tool_result.replace("Dane z Rejestru: ", "").split(", ")
            for part in parts:
                answer += f"- {part}\n"
            answer += "\n"

    if context:
        answer += "#### Znalezione ostrzeżenia i interakcje:\n"
        
        raw_chunks = context.split("[Źródło ID:")
        processed_chunks = []
        for chunk in raw_chunks:
            if not chunk.strip(): continue
            if "]" in chunk:
                processed_chunks.append(chunk.split("]", 1)[-1].strip())
            else:
                processed_chunks.append(chunk.strip())

        query_words = set(re.findall(r'\w+', query.lower()))
        common_words = {"czy", "mogę", "brać", "mieszać", "z", "i", "po", "leku", "leki", "interakcje", "stosować", "razem"}
        drug_keywords = query_words - common_words

        try:
            with open("knowledge.txt", "r", encoding="utf-8") as f:
                k_data = f.read().split("\n\n")
                for block in k_data:
                    b_name = ""
                    b_subs = ""
                    b_group = ""
                    is_drug = any(t in block for t in ["Typ: Lek", "Typ: Lek złożony", "Typ: Używka"])
                    for b_line in block.split("\n"):
                        if b_line.startswith("Nazwa:"): b_name = b_line.split(":", 1)[1].strip().lower()
                        if b_line.startswith("Substancja:") or b_line.startswith("Substancje:"): b_subs = b_line.split(":", 1)[1].strip().lower()
                        if b_line.startswith("Grupa:"): b_group = b_line.split(":", 1)[1].strip().lower()
                    
                    if is_drug:

                        is_match = b_name and any(k in b_name or b_name in k for k in drug_keywords)
                        if not is_match and b_subs:
                            is_match = any(k in b_subs for k in drug_keywords)
                        
                        if not is_match and b_group:
                             is_match = any(k in b_group or b_group in k for k in drug_keywords)

                        if is_match:
                            if b_name: drug_keywords.add(b_name)
                            for sw in re.findall(r'\w+', b_subs):
                                if len(sw) > 3: drug_keywords.add(sw)
                            for gw in re.findall(r'\w+', b_group):
                                if len(gw) > 3: 
                                    drug_keywords.add(gw)
                                    if gw.endswith("a") and len(gw) > 5:
                                        drug_keywords.add(gw[:-1] + "y")
                                    elif gw.endswith("y") and len(gw) > 5:
                                        drug_keywords.add(gw[:-1] + "a")
        except:
            pass
        identified_substances = set()
        if tool_result and "{" in tool_result:
            try:
                lines = tool_result.strip().split("\n")
                for line in lines:
                    if "{" in line:
                        json_part = "{" + line.split("{", 1)[-1]
                        data = json.loads(json_part)
                        for field in ['substance', 'name', 'commonName']:
                            val = data.get(field, '')
                            if val:
                                words = re.findall(r'\w+', val.lower())
                                for w in words:
                                    if len(w) >= 3: identified_substances.add(w)
            except:
                pass

        added_warnings = 0
        all_match_keywords = drug_keywords.union(identified_substances)
        
        for content in processed_chunks:
            content_lower = content.lower()
            
            show = False
            is_interaction = any(term in content_lower for term in ["typ: interakcja", "interakcja:", "podmioty:"])
            
            if is_interaction:
                matches = set()
                for k in all_match_keywords:
                    if re.search(r'\b' + re.escape(k) + r'\b', content_lower):
                        matches.add(k)
                
                if len(matches) >= 2:
                    show = True
            else:
                for line in content.split("\n"):
                    if any(line.strip().startswith(p) for p in ["Nazwa:", "Substancja:", "Substancje:", "Grupa:"]):
                        line_low = line.lower()
                        if any(re.search(r'\b' + re.escape(k) + r'\b', line_low) for k in all_match_keywords):
                            show = True
                            break
            
            if show:
                lines = content.split("\n")
                important_info = []
                for line in lines:
                    line_strip = line.strip()
                    if any(line_strip.startswith(prefix) for prefix in ["Nazwa:", "Substancja:", "Ostrzeżenia:", "Podmioty:", "Nasilenie:", "Skutek:", "Skład:", "Substancje:", "Grupa:"]):
                        important_info.append(line_strip)
                
                has_details = any(any(prefix in info for prefix in ["Ostrzeżenia:", "Skutek:", "Nasilenie:", "Skład:", "Substancje:", "Grupa:"]) for info in important_info)
                
                if important_info and (has_details or is_interaction):
                    cleaned_info = []
                    for info in important_info:
                        for prefix in ["Ostrzeżenia:", "Skutek:", "Nasilenie:", "Podmioty:", "Skład:", "Substancje:", "Grupa:", "Nazwa:", "Substancja:"]:
                            if info.startswith(prefix):
                                val = info.split(":", 1)[1].strip()
                                if val:
                                    cleaned_info.append(f"**{prefix[:-1]}:** {val}")
                                break
                    
                    if cleaned_info:
                        formatted_item = " | ".join(cleaned_info)
                        if formatted_item not in answer:
                            answer += f"- {formatted_item}\n"
                            added_warnings += 1
        
        if added_warnings == 0:
            answer += "Brak specyficznych ostrzeżeń dla tego zestawienia w lokalnej bazie.\n"
        answer += "\n"
    else:
        answer += "#### Informacja:\n"
        answer += "Brak specyficznych ostrzeżeń w lokalnej bazie danych dla tego zapytania.\n\n"

    answer += "---\n"
    answer += "UWAGA: System podaje dane z rejestrów i bazy wiedzy. "
    answer += "Zawsze skonsultuj się z lekarzem przed zmianą dawkowania lub łączeniem leków."

    return answer

def log_to_csv(query, mode, drugs, rag_status, answer_length):
    file_path = "logs_aggregate.csv"
    file_exists = os.path.isfile(file_path)
    
    try:
        with open(file_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "query", "mode", "detected_drugs", "rag_status", "answer_length"])
            
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                query,
                mode,
                ", ".join(drugs) if drugs else "None",
                rag_status,
                answer_length
            ])
    except Exception as e:
        logger.error(f"Błąd zapisu do CSV: {e}")


@app.post("/ask", response_model=QueryResponse)
async def ask_endpoint(request: QueryRequest):
    logs = []
    query = request.query
    logs.append(f"Zapytanie: {query}")

    is_attack, msg = SecurityGuard.check_injection(query)
    if is_attack:
        logger.warning(f"Zablokowano atak: {msg}")
        raise HTTPException(status_code=400, detail=msg)

    clean_query = SecurityGuard.sanitize_input(query)

    logs.append("Weryfikacja bezpieczeństwa: OK")

    tool_result = ""
    all_tool_results = []
    potential_drugs = []

    extraction_prompt = f"""Wypisz TYLKO nazwy leków lub substancji czynnych występujące w poniższym zapytaniu, w mianowniku liczby pojedynczej, oddzielone przecinkami. 
Przykłady: 
- 'Doretę' -> 'Doreta'
- 'Xanaxem' -> 'Xanax'
- 'Paracetamolu' -> 'Paracetamol'

WAŻNE: 
- Popraw oczywiste literówki. 
- Zwróć tylko nazwy, bez żadnych dodatkowych słów.
- NIE traktuj czasowników takich jak 'mieszać', 'brać', 'stosować', 'używać', 'łączyć' jako nazw leków. 
- Jeśli nie ma nazw leków, zwróć puste pole.
Zapytanie: {clean_query}"""

    if request.mode == "local":
        extraction_modes = ["groq", "gemini"]
    else:
        extraction_modes = [request.mode]

    for ex_mode in extraction_modes:
        try:
            llm_extracted = ""
            if ex_mode == "gemini":
                gemini_key = os.getenv("GEMINI_API_KEY")
                if gemini_key:
                    client = genai.Client(api_key=gemini_key)
                    ex_res = client.models.generate_content(model='gemini-2.0-flash', contents=extraction_prompt)
                    llm_extracted = ex_res.text.strip()
            elif ex_mode == "groq":
                groq_key = os.getenv("GROQ_API_KEY")
                if groq_key:
                    from groq import Groq
                    client = Groq(api_key=groq_key)
                    completion = client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[{"role": "user", "content": extraction_prompt}],
                        temperature=0,
                        max_tokens=100,
                    )
                    llm_extracted = completion.choices[0].message.content.strip()

            if llm_extracted:
                llm_extracted = llm_extracted.replace("- ", "").replace("* ", "").replace(".", "").replace("\n", ",")
                potential_drugs = [d.strip() for d in llm_extracted.split(",") if len(d.strip()) >= 3]
                if potential_drugs:
                    logs.append(f"Wykryte leki ({ex_mode}): {potential_drugs}")
                    break
        except Exception as e:
            logger.error(f"Błąd ekstrakcji ({ex_mode}): {e}")
            logs.append(f"Błąd ekstrakcji leków ({ex_mode}): {handle_genai_error(e)}")

    if not potential_drugs:
        words = clean_query.split()
        for word in words:
            clean_word = word.strip("?,.!")
            if len(clean_word) < 3: continue

            base_word = clean_word
            for suffix in ["em", "u", "a"]:
                if clean_word.endswith(suffix) and len(clean_word) > len(suffix) + 2:
                    base_word = clean_word[:-len(suffix)]
                    break

            if base_word[0].isupper() or len(base_word) >= 5:
                if base_word.lower() not in ["czy", "mogę", "brać", "jak", "jest", "razem", "podaj", "skład", "leku", "mieszać", "stosować", "łączyć", "używać"]:
                    potential_drugs.append(base_word)

    potential_drugs = list(dict.fromkeys(potential_drugs))

    if (request.mode == "gemini" or request.mode == "groq") and request.use_functions:
        try:
            if "Podaj skład leku" in clean_query or request.mode == "groq":
                for drug in potential_drugs:
                    dose_hint = None
                    if " dawka " in clean_query.lower():
                        dose_hint = clean_query.lower().split(" dawka ")[-1].strip()
                    elif " dawki " in clean_query.lower(): 
                        dose_hint = clean_query.lower().split(" dawki ")[-1].strip()
                    
                    res = registry.validate_and_execute("identify_drugs", {"drug_name": drug, "drug_dose": dose_hint, "mode": request.mode})
                    all_tool_results.append(res)
                    logs.append(f"Dane z rejestru dla {drug}: {res}")
                tool_result = "\n".join(all_tool_results)
            
            elif request.mode == "gemini" and "Podaj skład leku" in clean_query:
                 for drug in potential_drugs:
                    res = registry.validate_and_execute("identify_drugs", {"drug_name": drug, "mode": request.mode})
                    all_tool_results.append(res)
                    logs.append(f"Dane z rejestru dla {drug}: {res}")
                 tool_result = "\n".join(all_tool_results)
        except Exception as e:
            logs.append(f"Błąd: {str(e)}")
            tool_result = "Błąd komunikacji."

    elif request.mode == "local" and request.use_functions:
        if potential_drugs:
            for drug in potential_drugs:
                res = registry.validate_and_execute("identify_drugs", {"drug_name": drug, "mode": request.mode})
                all_tool_results.append(res)
                logs.append(f"Wynik narzędzia ({drug}): {res}")

            tool_result = "\n".join(all_tool_results)

    rag_query = clean_query

    if all_tool_results:
        substances_found = []
        for res in all_tool_results:
            if "Dane z Rejestru: {" in res:
                try:
                    json_data = json.loads(res.split("Dane z Rejestru: ")[1])
                    substances_found.append(json_data.get("substance", ""))
                    substances_found.append(json_data.get("name", ""))
                except:
                    pass
            elif "Substancja czynna:" in res:
                sub_part = res.split("Substancja czynna:")[1].split(",")[0].strip()
                substances_found.append(sub_part)

        rag_query += " " + " ".join(substances_found)

    rag_context = rag_system.search(rag_query, k=15)
    logs.append(f"Kontekst RAG pobrany.")

    if request.mode == "gemini" or request.mode == "groq":
        try:
            final_answer = call_llm(clean_query, f"{rag_context}\nInfo: {tool_result}", mode=request.mode,
                                    tools_schema=True, json_mode=request.json_mode)

            if hasattr(final_answer, 'content') and final_answer.content is not None:
                final_answer = final_answer.content
            elif not isinstance(final_answer, str):
                final_answer = str(final_answer)

        except Exception as e:
            logger.error(f"Błąd syntezy: {e}")
            final_answer = f"Usługa niedostępna: {str(e)}"
    else:
        final_answer = local_llm_stub(clean_query, rag_context, tool_result)

    if not request.json_mode:
        final_answer = SecurityGuard.validate_output(final_answer)
    
    log_to_csv(
        query=query,
        mode=request.mode,
        drugs=potential_drugs,
        rag_status="Success" if rag_context else "Empty",
        answer_length=len(final_answer)
    )
    
    return QueryResponse(answer=final_answer, logs=logs)


