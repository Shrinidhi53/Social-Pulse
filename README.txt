SOCIAL PULSE — STEP-BY-STEP LOCAL RUN GUIDE
============================================================

This guide starts the Social Pulse backend and frontend on Windows. Keep both terminal windows open while using the application.

REQUIREMENTS
------------
1. Windows 10 or 11.
2. Python 3.12 available as the `py` launcher (`py -3.12 --version`).
3. Node.js 20.19+ or 22.12+ with npm (`node --version`, `npm --version`).
4. Ollama is optional for collecting and viewing data. It is needed for local AI analysis and reply/content draft generation.
5. Internet access and valid provider credentials are needed for their corresponding external data sources.

FIRST-TIME SETUP
-----------------
1. Open PowerShell in the Social Pulse project folder.
   Example:
   cd "$HOME\OneDrive\Desktop\social pulse"

2. Create a Python virtual environment in the project root:
   py -3.12 -m venv .venv

3. Activate the environment:
   .\.venv\Scripts\Activate.ps1
   If PowerShell blocks activation, run this once in that terminal and activate again:
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

4. Install backend packages:
   python -m pip install -r backend\requirements.txt

5. Create the backend configuration file:
   Copy-Item backend\.env.example backend\.env
   Open backend\.env in a text editor and add keys for the providers you want to use. Keep this file private and do not commit or share it. Bluesky and GDELT use public endpoints; GNews, YouTube and SerpApi require their own credentials. Google Custom Search is optional and disabled by default.

6. Install frontend packages:
   Set-Location frontend
   npm install
   Set-Location ..

7. (Optional) Install/start Ollama and download the configured models:
   ollama pull phi3:3.8b
   ollama pull llama3.1:8b
   Make sure the Ollama application/service is running. Model downloads can be large. The model names can be changed in backend\.env.

START THE APP
-------------
1. Open Terminal / PowerShell window 1 in the project root.
2. Start the backend API:
   cd backend
   python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
3. Leave this window open. The backend API is at:
   http://127.0.0.1:8000
   Interactive API documentation:
   http://127.0.0.1:8000/docs

4. Open a second Terminal / PowerShell window in the project root.
5. Start the frontend:
   cd frontend
   npm run dev -- --host 127.0.0.1
6. Leave this window open and open this address in a browser:
   http://127.0.0.1:5173/

USING THE APP
-------------
1. Check the Overview. Brand sentiment summarizes analyzed public Tata STRIVE posts/comments for the selected recent window (7, 30 or 90 days). It excludes simulated examples and likely duplicate records. Publication date is used where available; otherwise the first collection date is used.
2. Use “Review mentions” to open Conversations filtered to that brand sentiment and the last 30 days.
3. Use the sentiment action button to open its suggested work area: for example, complaints go to Engagement Queue, positive signals go to Content & Growth, and mixed signals go to Insights. Review evidence before acting; sentiment is an estimate.
4. Select “Fetch data” in the app header to run collection for enabled sources. While the frontend is open and visible, scheduled collection runs every 30 minutes. The dashboard refreshes from the backend periodically. Closing the frontend stops its scheduled collection.
5. Analyze eligible records before expecting sentiment and audience insights. AI drafting requires Ollama and the configured models; dashboard collection and browsing can still work without Ollama.

CHECK THAT SERVICES ARE RUNNING
-------------------------------
Backend health:
   http://127.0.0.1:8000/health
The response reports database and Ollama/model availability.

If the page says the API cannot be reached, confirm the backend terminal is still running on port 8000. If the browser cannot open the app, confirm Vite is running on port 5173.

TROUBLESHOOTING
---------------
- “py is not recognized” or Python 3.12 is missing: install Python 3.12 and enable the Python launcher, then reopen PowerShell.
- “npm is not recognized”: install Node.js and reopen PowerShell.
- Port 8000 or 5173 is already in use: stop the older app process, or choose another port. If the API port changes, set VITE_API_BASE_URL in frontend\.env.local to the matching API URL and restart Vite.
- No live records: configure valid source keys in backend\.env, check each source's collection history, then use Fetch data. Public APIs may return no records due to quotas, query coverage, or source availability.
- No sentiment results: collect and analyze original public social posts/comments. Search snippets/news and simulated records are not audience sentiment evidence.
- Ollama is disconnected: start Ollama and check http://localhost:11434. Pull the model names listed by /health or in backend\.env.
- Python dependency changes: activate the virtual environment and rerun `python -m pip install -r backend\requirements.txt`.
- Frontend dependency changes: run `npm install` from the frontend folder.

STOPPING
--------
Press Ctrl+C in the frontend terminal and then Ctrl+C in the backend terminal. The local SQLite database is stored under the backend folder by default and is preserved between runs.

