# Asystent Interakcji między lekami - KnowYourPill

Asystent **KnowYourPill** pomoże znaleźć interakcje między lekami, a także stworzyć własną apteczkę leków, dzięki
czemu można w łatwy sposób sprawdzić, czy przyjmowane przez nas leki wchodzą ze sobą w interakcję!

Użyte technologie:
> — Backend: Python 3.11, FastAPI, Uvicorn, Pydantic, Docker, Docker Compose
> — Frontend: Streamlit
> — LLM/AI: Groq API, Gemini, Tryb lokalny

### Instalacja/Uruchomienie

1. Sklonuj repozytorium
2. Skopiuj .env.template -> .env.local
   ```cp .env.template .env.local```
3. Uzupełnij klucze API (sugerowany groq)
4. Zbuduj i uruchom kontener:
   ```docker-compose up --build```
5.  Otwórz aplikacje:
   ``http://localhost:8501/`` - dla frontendu
   ``http://localhost:8000/docs`` - dla backendu

### Instalacja lokalnie
1. ```pip install -r requirements.txt```
2. ustaw klucze w .env.local
3. Uruchom backend uvicorn main:app --reload --port 8000
4. Uruchom frontend streamlit run frontend.py

### DEMO MOŻLIWOŚCI APLIKACJI
## 1. Znajdź interakcje między lekami
![Interakcje](https://github.com/user-attachments/assets/8267dd96-4d6d-4700-9dd0-0ff488673e4c)
## 2. Dodawaj leki do swojej apteczki

![Apteczka1](https://github.com/user-attachments/assets/77ab3d36-dbac-465d-9d70-57bb2a6cc532)
## 3. Sprawdź interakcje bezpośrednio w swojej apteczce:

![Apteczka2](https://github.com/user-attachments/assets/fb5da9cd-61ff-4fc6-a95f-ab665abfa553)
