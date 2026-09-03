# Gmail Spend Intelligence

A local dashboard that reads Gmail transaction emails, extracts spending records,
and presents categories, recurring payments, trends, and anomalies. Every
transaction links back to its source Gmail message.

The app requests **read-only** Gmail access. It cannot send, modify, or delete
email.

## Architecture

```text
Browser
  | http://localhost:8501
  v
Streamlit dashboard -- internal HTTP --> FastAPI API --> MongoDB
  |                                      |
  | OAuth redirect                       +--> Gmail API (read-only)
  +----------------------------> Google  +--> Gemini API (optional extraction)
```

| Service | Port | Responsibility |
| --- | ---: | --- |
| Streamlit frontend | 8501 | Dashboard, OAuth launch, sync controls |
| FastAPI backend | 8000 | OAuth, Gmail sync, extraction, analytics API |
| MongoDB | 27017 (internal) | Encrypted OAuth token and transaction storage |

## Prerequisites

- Docker Desktop with Docker Compose, recommended; or Python 3.12+ and MongoDB 7+
- A Google Cloud project with Gmail API enabled
- Google OAuth 2.0 **Web application** credentials
- Optional: a Gemini API key for LLM-assisted extraction. Without one, the
  deterministic rule-based extractor is used.

## Google Cloud setup

1. In your Google Cloud project, enable **Gmail API**.
2. Create an OAuth 2.0 client of type **Web application**.
3. Add this exact authorized redirect URI:

   ```text
   http://localhost:8000/auth/google/callback
   ```

4. Configure the OAuth consent screen. While its publishing status is
   **Testing**, add every Gmail account you want to connect under **Test users**.
5. Copy the client ID and client secret into `backend/.env`.

> Gmail read access is a sensitive Google scope. For a personal/local project,
> use Testing mode with the relevant accounts listed as test users. Publishing
> to arbitrary users requires Google's OAuth verification process.

## Run with Docker Compose

1. Create your private environment file:

   ```powershell
   Copy-Item backend/.env.example backend/.env
   ```

2. Edit `backend/.env` and set at least:

   ```dotenv
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret
   GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

   # Optional: omit the key or set MOCK_LLM=true for rule-based extraction.
   GEMINI_API_KEY=your-gemini-key
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```

3. Start all services:

   ```powershell
   docker compose up --build
   ```

4. Open the dashboard at <http://localhost:8501>. API docs are at
   <http://localhost:8000/docs>.

The first startup creates two persistent Docker volumes:

- `mongo-data` retains MongoDB data.
- `backend-secrets` retains the generated Fernet encryption key used for OAuth
  tokens.

Useful commands:

```powershell
# Run in the background
docker compose up --build -d

# Follow service logs
docker compose logs -f backend

# Stop containers while retaining data
docker compose down

# Remove containers and all local application data (irreversible)
docker compose down -v
```

## Run without Docker

Start MongoDB locally, then in two PowerShell terminals from the repository root:

```powershell
# Terminal 1: backend
.\.venv\Scripts\Activate.ps1
Set-Location backend
uvicorn app.main:app --reload --port 8000
```

```powershell
# Terminal 2: frontend
.\.venv\Scripts\Activate.ps1
$env:BACKEND_URL = "http://localhost:8000"
Set-Location frontend
streamlit run app.py
```

If you have not created the virtual environment yet:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

## First sync

1. Open the dashboard and select **Connect Gmail**.
2. Complete Google consent. The dashboard shows the connected email address.
3. Select the lookback period and press **Sync now**.
4. The backend searches relevant Gmail messages, extracts transaction candidates,
   and stores only new messages. Re-running sync is safe: `gmail_message_id` is
   unique.

The default sync checks six months and up to 150 emails. Adjust `DEFAULT_MONTHS`
and `MAX_EMAILS` in `backend/.env` if needed.

## Configuration reference

| Variable | Required | Description |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID` | Yes for Gmail | OAuth web client ID |
| `GOOGLE_CLIENT_SECRET` | Yes for Gmail | OAuth web client secret |
| `GOOGLE_REDIRECT_URI` | Yes for Gmail | Must exactly match Google Cloud configuration |
| `GEMINI_API_KEY` | No | Enables Gemini extraction |
| `GEMINI_MODEL` | No | Defaults to `gemini-3.5-flash-lite` |
| `MOCK_LLM` | No | Set `true` to force rule-based extraction |
| `MONGODB_URI` | No | Local default is `mongodb://localhost:27017`; Compose overrides it internally |
| `MONGODB_DB` | No | Database name, default `gmail_spend` |
| `FRONTEND_ORIGIN` | No | Public frontend origin for CORS and OAuth return, default `http://localhost:8501` |

Never commit `backend/.env` or `backend/.secrets`. Both are excluded from Git and
Docker build contexts.

## API and health checks

- `GET /health` - API and MongoDB health
- `GET /docs` - interactive OpenAPI docs
- `GET /auth/status` - OAuth configuration and connection state
- `POST /sync` - fetch and extract Gmail transactions
- `GET /transactions`, `GET /profile`, `GET /insights` - dashboard data

## Tests

From `backend`:

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```

The integration tests use a temporary MongoDB database named
`gmail_spend_apitest`; if MongoDB is unavailable, those tests are skipped.
