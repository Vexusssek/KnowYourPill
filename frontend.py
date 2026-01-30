import streamlit as st
import requests
import json
import os
import base64
from io import BytesIO
from PIL import Image
from datetime import time

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="Know Your Pill", layout="wide")

DB_FILE = "my_drugs.json"


def load_drugs():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Błąd podczas ładowania bazy leków: {e}")
            return []
    return []


def save_drugs(drugs):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(drugs, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"Błąd podczas zapisywania bazy leków: {e}")


st.markdown("""
    <style>

    footer {visibility: hidden;}
    header {visibility: hidden;}
    .st-emotion-cache-15z92p2, 
    .st-emotion-cache-kg9bc1,
    .st-emotion-cache-1f3w0ua,
    button[title="View source"], 
    button[title="Copy to clipboard"],
    .stHeader a,
    header button,
    a.anchor-link,
    .element-container:has(h1) a,
    h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {
        display: none !important;
    }
    h1 {
        color: #fffff0 !important;
        text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)
st.markdown("<h1>Know Your Pill: Asystent Interakcji między lekami</h1>", unsafe_allow_html=True)

tab_asystent, tab_apteczka, tab_ustawienia = st.tabs(["Asystent", "Moja apteczka", "Tryb modelu"])

with tab_ustawienia:
    st.header("Ustawienia modelu")
    mode = st.selectbox("Tryb Modelu", ["groq", "gemini", "local"], index=0)
    use_tools = st.checkbox("Używaj Function Calling", value=True)

st.markdown("---")

with tab_asystent:
    query = st.text_input("Zadaj pytanie o lek (np. 'Czy mogę brać Ibuprofen z Paracetamolem?')")

    if st.button("Zapytaj"):
        if not query:
            st.warning("Wpisz pytanie.")
        else:
            with st.spinner("Analiza..."):
                try:
                    payload = {
                        "query": query,
                        "mode": mode,
                        "use_functions": use_tools
                    }
                    response = requests.post(f"{API_URL}/ask", json=payload)

                    if response.status_code == 200:
                        data = response.json()
                        answer = data["answer"]
                        
                        if answer.startswith("INTERAKCJA:"):
                            st.error("Znaleziono potencjalne interakcje!")
                            st.write(answer.replace("INTERAKCJA:", "").strip())
                        elif answer.startswith("BEZPIECZNIE:"):
                            st.success("Nie znaleziono potencjalnych interakcji.")
                            st.write(answer.replace("BEZPIECZNIE:", "").strip())
                        else:
                            st.info("Odpowiedź systemu:")
                            st.write(answer)

                        with st.expander("Szczegóły techniczne"):
                            for log in data["logs"]:
                                st.text(f"> {log}")
                    else:
                        st.error(f"Błąd API: {response.text}")

                except requests.exceptions.ConnectionError:
                    st.error("Nie można połączyć się z serwerem Backend. Uruchom 'uvicorn main:app'.")

with tab_apteczka:
    st.markdown("Zarządzaj swoimi lekami i sprawdzaj ich interakcje.")

    if "my_drugs" not in st.session_state:
        st.session_state.my_drugs = load_drugs()

    with st.expander("Dodaj nowy lek", expanded=not st.session_state.my_drugs):
        with st.form("add_drug_form"):
            col1, col2 = st.columns(2)
            with col1:
                drug_name = st.text_input("Nazwa leku (np. Paracetamol, Apap)")
                dose = st.text_input("Twoja dawka (np. 1 tabletka, 500mg)")
            with col2:
                freq = st.multiselect("Dni przyjmowania", ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Niedz"],
                                      default=["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Niedz"])
                st.write("Godziny przyjmowania (oddzielone przecinkiem, np. 08:00, 17:00)")
                times_input = st.text_input("Godziny", "08:00")

            submit_drug = st.form_submit_button("Dodaj do apteczki")

            if submit_drug and drug_name:
                try:
                    raw_times = [t.strip() for t in times_input.split(",")]
                    times_list = []
                    for rt in raw_times:
                        if ":" in rt:
                            times_list.append(rt)
                        else:
                            st.error(f"Niepoprawny format godziny: {rt}")

                    if not times_list:
                        times_list = ["08:00"]
                except:
                    times_list = ["08:00"]

                with st.spinner(f"Pobieranie informacji o {drug_name}..."):
                    try:
                        payload = {"query": f"Podaj skład leku {drug_name} dawka {dose}", "mode": mode, "use_functions": True}
                        response = requests.post(f"{API_URL}/ask", json=payload)
                        gov_info = "Brak danych z rejestru."
                        official_name = drug_name
                        official_power = dose

                        if response.status_code == 200:
                            data = response.json()
                            logs = data.get("logs", [])
                            for log in logs:
                                if "Dane z rejestru dla" in log:
                                    gov_info = log.split(": ", 1)[-1]
                                    break
                                elif "Dane z Rejestru:" in log or "Tool Result" in log or "Retry Tool Result" in log:
                                    if "Result: " in log:
                                        gov_info = log.split("Result: ")[-1]
                                    elif "Tool Result" in log:
                                        gov_info = log.split(": ", 1)[-1]
                                    else:
                                        gov_info = log
                                    break
                            

                            if gov_info == "Brak danych z rejestru." and data.get("answer"):

                                if "Podaj skład leku" in query:
                                     gov_info = data["answer"]

                        image_url = None
                        try:
                            if "{" in gov_info:
                                import json
                                start_idx = gov_info.find('{')
                                end_idx = gov_info.rfind('}')
                                if start_idx != -1 and end_idx != -1:
                                    json_str = gov_info[start_idx:end_idx+1]
                                    gov_json = json.loads(json_str)
                                    official_name = gov_json.get("name", drug_name)
                                    official_power = gov_json.get("power", dose)
                        except:
                            pass

                        st.session_state.my_drugs.append({
                            "name": drug_name,
                            "dose": dose,
                            "days": freq,
                            "times": times_list,
                            "gov_info": gov_info,
                            "image_url": image_url,
                            "custom_image": None
                        })
                        save_drugs(st.session_state.my_drugs)
                        st.success(f"Dodano {drug_name} do apteczki.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Błąd podczas dodawania: {e}")

    if st.session_state.my_drugs:
        st.subheader("Twoje leki")
        for i, drug in enumerate(st.session_state.my_drugs):
            drug_times = drug.get('times', [drug.get('time', '08:00')])
            
            gov_data = {}
            if "gov_info" in drug and drug["gov_info"]:
                info_text = drug["gov_info"]
                
                try:
                    start_idx = info_text.find('{')
                    end_idx = info_text.rfind('}')
                    if start_idx != -1 and end_idx != -1:
                        json_str = info_text[start_idx:end_idx+1]
                        gov_data = json.loads(json_str)
                except Exception as e:
                    if "Dane z Rejestru: " in info_text:
                        json_part = info_text.split("Dane z Rejestru: ", 1)[-1]
                        try:
                            gov_data = json.loads(json_part)
                        except:
                            pass
                    elif "{" in info_text:
                        try:
                            json_part = info_text.split("{", 1)[-1]
                            gov_data = json.loads("{" + json_part)
                        except:
                            pass

            with st.expander(f"{drug['name']} - {drug['dose']}"):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.write(f"**Dawka:** {drug['dose']}")
                    st.write(f"**Dni:** {', '.join(drug['days'])}")
                    st.write(f"**Godziny:** {', '.join(drug_times)}")

                    if gov_data:
                        st.markdown("---")
                        st.markdown("**Informacje z Rejestru Produktów Leczniczych:**")
                        st.write(f"**Oficjalna nazwa:** {gov_data.get('name', 'N/A')}")
                        st.write(f"**Substancja czynna:** {gov_data.get('substance', 'N/A')}")
                        st.write(f"**Moc/Dawka:** {gov_data.get('power', 'N/A')}")
                        st.write(f"**Postać:** {gov_data.get('form', 'N/A')}")
                        st.write(f"**Kod ATC:** {gov_data.get('atc', 'N/A')}")

                        indications = gov_data.get('indications', '')
                        if indications and indications != "Brak informacji o wskazaniach w rejestrze." and indications != "Brak szczegółowych informacji o wskazaniach w skróconym rejestrze.":
                            st.write(f"**Wskazania:** {indications}")
                    elif drug.get("gov_info"):
                        st.markdown("---")
                        clean_info = drug["gov_info"]
                        if "Wynik narzędzia" in clean_info:
                            if "): " in clean_info:
                                clean_info = clean_info.split("): ", 1)[-1]
                            elif ": " in clean_info:
                                clean_info = clean_info.split(": ", 1)[-1]

                        if "Link do zdjęć:" in clean_info:
                            clean_info = clean_info.split("Link do zdjęć:")[0].strip()
                            if clean_info.endswith(","):
                                clean_info = clean_info[:-1]

                        st.text(clean_info)
                
                with col2:
                    displayed_image = False

                    if gov_data.get("image_url") or drug.get("image_url"):
                        img_url = gov_data.get("image_url") or drug.get("image_url")
                        try:
                            st.image(img_url, width='stretch')
                            displayed_image = True
                        except:
                            pass

                    if drug.get("custom_image"):
                        try:
                            st.image(drug["custom_image"], width='stretch')
                            displayed_image = True
                            if st.button("Usuń własne zdjęcie", key=f"del_img_{i}"):
                                drug["custom_image"] = None
                                save_drugs(st.session_state.my_drugs)
                                st.rerun()
                        except:
                            st.error("Błąd ładowania zdjęcia.")

                    if not displayed_image:
                        st.caption("Brak zdjęcia")

                    uploaded_file = st.file_uploader("Wgraj własne zdjęcie", type=["jpg", "jpeg", "png"], key=f"upload_{i}")
                    if uploaded_file is not None:
                        img = Image.open(uploaded_file)
                        img.thumbnail((400, 400))
                        buffered = BytesIO()
                        img.save(buffered, format="PNG")
                        img_str = base64.b64encode(buffered.getvalue()).decode()
                        drug["custom_image"] = f"data:image/png;base64,{img_str}"
                        save_drugs(st.session_state.my_drugs)
                        st.rerun()

                    st.markdown("---")
                    if st.button("Usuń lek z apteczki", key=f"del_{i}", type="primary"):
                        st.session_state.my_drugs.pop(i)
                        save_drugs(st.session_state.my_drugs)
                        st.rerun()

        if st.button("Sprawdź interakcje w mojej apteczce"):
            if len(st.session_state.my_drugs) < 2:
                st.info("Dodaj co najmniej dwa leki, aby sprawdzić interakcje między nimi.")
            else:
                names = [d["name"] for d in st.session_state.my_drugs]
                query_all = f"Czy występują interakcje między lekami: {', '.join(names)}?"

                with st.spinner("Analiza całej apteczki..."):
                    try:
                        payload = {
                            "query": query_all,
                            "mode": mode,
                            "use_functions": use_tools
                        }
                        response = requests.post(f"{API_URL}/ask", json=payload)
                        if response.status_code == 200:
                            data = response.json()
                            answer = data["answer"]
                            st.subheader("Analiza interakcji w apteczce")
                            
                            if answer.startswith("INTERAKCJA:"):
                                st.error("Znaleziono potencjalne interakcje!")
                                st.write(answer.replace("INTERAKCJA:", "").strip())
                            elif answer.startswith("BEZPIECZNIE:"):
                                st.success("Nie znaleziono potencjalnych interakcji.")
                                st.write(answer.replace("BEZPIECZNIE:", "").strip())
                            else:
                                st.warning(answer)
                        else:
                            st.error("Błąd podczas sprawdzania interakcji.")
                    except:
                        st.error("Błąd połączenia.")
