import streamlit as st
import requests
import json
import os
from datetime import time

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
    #MainMenu {visibility: hidden;}
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
    mode = st.selectbox("Tryb Modelu", ["gemini", "local"])
    use_tools = st.checkbox("Używaj Function Calling", value=True)

st.markdown("---")

with tab_asystent:
    query = st.text_input("Zadaj pytanie o lek (np. 'Czy mogę brać Paracetamol z alkoholem?')")

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
                    response = requests.post("http://127.0.0.1:8000/ask", json=payload)

                    if response.status_code == 200:
                        data = response.json()
                        st.success("Odpowiedź systemu:")
                        st.write(data["answer"])

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
                        payload = {"query": f"Podaj skład leku {drug_name}", "mode": mode, "use_functions": True}
                        response = requests.post("http://127.0.0.1:8000/ask", json=payload)
                        gov_info = "Brak danych z rejestru."
                        if response.status_code == 200:
                            logs = response.json().get("logs", [])
                            for log in logs:
                                if "Dane z Rejestru:" in log or "Tool Result" in log or "Retry Tool Result" in log:
                                    if "Result: " in log:
                                        gov_info = log.split("Result: ")[-1]
                                    elif "Tool Result" in log:
                                        gov_info = log.split(": ", 1)[-1]
                                    else:
                                        gov_info = log
                                    break

                        st.session_state.my_drugs.append({
                            "name": drug_name,
                            "dose": dose,
                            "days": freq,
                            "times": times_list,
                            "gov_info": gov_info
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

            with st.expander(f"{drug['name']} - {drug['dose']}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**Dni:** {', '.join(drug['days'])}")
                    st.write(f"**Godziny:** {', '.join(drug_times)}")
                    if "gov_info" in drug and drug["gov_info"]:
                        st.info(drug["gov_info"])
                with col2:
                    if st.button("Usuń", key=f"del_{i}"):
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
                        response = requests.post("http://127.0.0.1:8000/ask", json=payload)
                        if response.status_code == 200:
                            st.subheader("Analiza interakcji w apteczce")
                            st.warning(response.json()["answer"])
                        else:
                            st.error("Błąd podczas sprawdzania interakcji.")
                    except:
                        st.error("Błąd połączenia.")
