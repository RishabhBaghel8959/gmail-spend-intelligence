# Gmail Spend Intelligence

Gmail Spend Intelligence is a local-first financial-email analysis application.
With a user's explicit consent, it reads likely transaction emails from Gmail,
extracts structured transactions, and shows spending patterns, recurring payments,
and unusual charges. Each stored transaction includes a link back to its source
Gmail message for traceability.

The application separates the ingestion and analysis engine from the dashboard.
Gmail, AI, storage, and analytics logic live in the FastAPI backend, while the
Streamlit frontend presents the results.

## What it does

- Connects one Gmail account through Google OAuth using `gmail.readonly` only.
- Searches recent email for financial terms such as receipt, invoice, payment,
  subscription, bill, and order confirmation.
- Applies inexpensive deterministic rules before Gemini, reducing LLM calls for
  marketing and non-transaction email.
- Extracts merchant, amount, currency, date, category, transaction type, and
  confidence from likely financial email.
- Stores only new transactions, using the Gmail message ID as a unique key.
- Shows category and merchant breakdowns, monthly trends, recurring payments,
  and deterministic anomaly insights.
- Links each displayed transaction to the original Gmail message.

## Architecture

```text
                         Google OAuth consent
Browser --------------------------+----------------------------------> Google
  |                               |                                     |
  | http://localhost:8501         +-- callback: http://localhost:8000   |
  v                                                                     |
Streamlit dashboard -- HTTP --> FastAPI backend -- read-only Gmail API -+
                                  |          |
                                  |          +--> Gemini API (optional)
                                  v
                                MongoDB
```

### Sync pipeline

```text
Gmail query
  -> fetch message headers and body
  -> deterministic transaction-candidate rules
  -> Gemini JSON extraction (or rule-based fallback)
  -> normalize merchant, date, amount, category, and type
  -> idempotent MongoDB upsert
  -> profile, recurring-payment, and anomaly analytics
  -> Streamlit dashboard
```

The LLM is used for the fuzzy task: extracting transaction details from varied
email wording. Filtering, normalization, deduplication, storage, and analytics
remain deterministic and testable.

## Actual tech stack

| Area | Technology used in this project |
| --- | --- |
| Backend API | Python, FastAPI, Uvicorn |
| Dashboard | Streamlit, Pandas, Plotly |
| Database | MongoDB with Motor/PyMongo |
| OAuth and Gmail | `google-auth-oauthlib`, Google Gmail API client |
| LLM extraction | Google Gemini through `google-genai` |
| Validation and settings | Pydantic and `pydantic-settings` |
| Email body parsing | BeautifulSoup and lxml |
| Token encryption | Fernet from `cryptography` |
| Retry handling | Tenacity |
| Containers | Docker and Docker Compose |
| Tests | Pytest, FastAPI TestClient |

> The original implementation plan mentions SQLite, SQLModel, `frontend/api.py`,
> sample-mode fixtures, and `/api/*` routes. Those are **not** part of this
> implementation. The running project uses MongoDB, a single Streamlit app, real
> Gmail sync, and the routes documented below.

## Repository layout

```text
.
|- Dockerfile                 # Backend and frontend image targets
|- compose.yaml               # MongoDB, FastAPI, and Streamlit services
|- backend/
|  |- .env.example           # Environment-variable template
|  |- app/
|  |  |- auth/               # OAuth flow and Fernet encryption
|  |  |- gmail/              # Gmail query, fetch, MIME/body processing
|  |  |- extraction/         # Rules, Gemini, normalization, pipeline
|  |  |- analytics/          # Profile, recurring, and anomaly insights
|  |  |- routers/            # Auth, sync, transactions, insights routes
|  |  |- mongodb.py          # Shared Motor client and indexes
|  |  |- repository.py       # MongoDB reads and writes
|  |  `- main.py             # FastAPI application
|  `- tests/                 # Unit and API/integration tests
`- frontend/
   `- app.py                 # Streamlit dashboard
```

## Prerequisites

- Docker Desktop with Docker Compose (recommended), or Python 3.12+ and MongoDB 7+.
- A Google Cloud project with the Gmail API enabled.
- An OAuth 2.0 **Web application** client in that Google Cloud project.
- Optional: a Gemini API key. If omitted, the application uses rule-based
  extraction and does not call Gemini.

## Google Cloud configuration

1. Open the Google Cloud project that owns your OAuth client.
2. Enable the **Gmail API** under **APIs & Services**.
3. Create OAuth credentials of type **Web application**.
4. Add this exact entry to **Authorized redirect URIs**:

   ```text
   http://localhost:8000/auth/google/callback
   ```

5. Configure the OAuth consent screen.
6. While the OAuth app has a **Testing** publishing status, add each Gmail account
   that will use the app under **Test users**.

The redirect URI must match exactly. `localhost` and `127.0.0.1` are different
values to Google, and a trailing slash also changes the value.

Gmail access uses a sensitive scope. A local/personal project can stay in Testing
mode with the permitted accounts added as test users. Publishing to unrestricted
users requires Google's OAuth verification process.

## Configuration

Create the private configuration file:

```powershell
Copy-Item backend/.env.example backend/.env
```

Set the required OAuth values in `backend/.env`:

```dotenv
GOOGLE_CLIENT_ID=your-oauth-client-id
GOOGLE_CLIENT_SECRET=your-oauth-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
```

Optional Gemini configuration:

```dotenv
# Leave blank, or set MOCK_LLM=true, to use only deterministic extraction.
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-3.5-flash-lite
MOCK_LLM=false
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGODB_DB` | `gmail_spend` | MongoDB database name |
| `GOOGLE_CLIENT_ID` | none | OAuth web-client ID |
| `GOOGLE_CLIENT_SECRET` | none | OAuth web-client secret |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/auth/google/callback` | OAuth callback URL |
| `GEMINI_API_KEY` | none | Enables Gemini extraction |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini extraction model |
| `MOCK_LLM` | `false` | Force the local rule-based extraction path |
| `MAX_EMAILS` | `150` | Maximum emails scanned per sync |
| `DEFAULT_MONTHS` | `6` | Default Gmail lookback window |
| `BODY_CHAR_LIMIT` | `4000` | Maximum email-body characters sent to Gemini |
| `FRONTEND_ORIGIN` | `http://localhost:8501` | Streamlit origin for CORS and OAuth return |

Never commit `backend/.env` or `backend/.secrets`. They are excluded from Git and
the Docker build context.

## Run with Docker Compose

Docker Compose starts all three services:

| Service | Public URL/port | Notes |
| --- | --- | --- |
| Streamlit dashboard | <http://localhost:8501> | User interface |
| FastAPI backend | <http://localhost:8000> | API and OAuth callback |
| MongoDB | internal only | Not published to the host to avoid port conflicts |

Start the application from the repository root:

```powershell
docker compose up --build
```

Open the dashboard at <http://localhost:8501> and API documentation at
<http://localhost:8000/docs>.

Useful commands:

```powershell
# Start in the background
docker compose up --build -d

# Follow backend logs
docker compose logs -f backend

# Stop containers but retain transactions and the encryption key
docker compose down

# Remove containers, MongoDB data, and the generated encryption key (destructive)
docker compose down -v
```

Compose persists two named volumes:

- `mongo-data` stores transactions, sync history, and encrypted OAuth tokens.
- `backend-secrets` stores the generated Fernet key. Keeping it is necessary to
  decrypt existing stored OAuth tokens after containers are recreated.

The dashboard uses `http://backend:8000` internally in Docker, while browser OAuth
redirects use the public `http://localhost:8000` URL. This split is intentional:
Docker service names are not resolvable from the browser.

## Run locally without Docker

Ensure MongoDB is running locally, create `backend/.env` as above, then use two
PowerShell terminals from the repository root.

```powershell
# One-time setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

```powershell
# Terminal 1: FastAPI backend
.\.venv\Scripts\Activate.ps1
Set-Location backend
uvicorn app.main:app --reload --port 8000
```

```powershell
# Terminal 2: Streamlit dashboard
.\.venv\Scripts\Activate.ps1
$env:BACKEND_URL = "http://localhost:8000"
Set-Location frontend
streamlit run app.py
```

## First use

1. Open the dashboard at <http://localhost:8501>.
2. Select **Connect Gmail** and complete Google consent.
3. Return to the dashboard after the callback confirms the connected account.
4. Choose a lookback window and email limit, then select **Sync now**.
5. Review the profile, insights, recurring payments, and transaction table.
6. Use the **Open** link in a transaction row to open its Gmail source message.

Sync is idempotent: a second sync of the same Gmail messages does not duplicate
stored transactions.

## Extraction and analytics behavior

### Candidate filtering and extraction

The Gmail query reduces the initial mailbox search to financial-looking mail and
excludes Google Chat. The rule-based candidate filter then checks transaction
signals and amount/currency patterns. Only candidate emails are sent to Gemini
when Gemini is configured.

Gemini is asked for strict JSON fields: transaction status, merchant, amount,
currency, date, category, transaction type, and confidence. If Gemini is disabled
or fails, the pipeline falls back to the deterministic rules extractor. Temporary
API errors are retried; permanent client errors such as invalid model names are
not retried for every email.

### Analytics and insights

The backend calculates these from stored transactions:

- Total spending, category totals, top merchants, and monthly trend.
- Recurring payment candidates based on repeated merchants and monthly or weekly
  cadence, including an estimated next charge date.
- Highest-spending category and top merchant summaries.
- A warning when a merchant's latest payment is materially higher than its prior
  average.
- A warning for a large, first-seen merchant payment relative to typical spend.

Refunds and transfers are excluded from spend totals. Analytics use the account's
most common currency so amounts from different currencies are not added together.

## API reference

Interactive API documentation is available at `GET /docs`.

| Method | Route | Description |
| --- | --- | --- |
| `GET` | `/health` | Backend and MongoDB health status |
| `GET` | `/auth/status` | OAuth configuration and current connection state |
| `GET` | `/auth/google/login` | Starts Google OAuth login |
| `GET` | `/auth/google/callback` | OAuth callback endpoint |
| `POST` | `/auth/logout` | Deletes the stored OAuth token |
| `POST` | `/sync` | Fetches, extracts, and stores recent Gmail transactions |
| `GET` | `/sync/latest` | Most recent sync result |
| `GET` | `/transactions` | List transactions; supports category, source, dates, skip, and limit |
| `GET` | `/transactions/{txn_id}` | Retrieve one transaction |
| `GET` | `/profile` | Spending profile and recurring-payment data |
| `GET` | `/insights` | Informational insights and anomalies |

## Privacy and security

- The Gmail OAuth scope is `https://www.googleapis.com/auth/gmail.readonly`.
  The app cannot send, modify, label, archive, or delete messages.
- OAuth credentials are encrypted at rest with Fernet before being stored in
  MongoDB.
- OAuth state and PKCE verifier values are retained only in short-lived,
  HTTP-only cookies during login.
- The app keeps transaction fields plus source-email metadata needed for
  traceability. It does not store full raw Gmail MIME messages.
- When Gemini is enabled, candidate email sender, subject, date, and a trimmed
  body are sent to Gemini for extraction. Set `MOCK_LLM=true` or leave
  `GEMINI_API_KEY` blank to avoid third-party LLM calls.

## Testing

Run the test suite from the `backend` directory:

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```

The suite covers normalization, extraction rules, encryption, analytics,
OAuth/PKCE handling, API contracts, and idempotent sync behavior. API tests use
the isolated `gmail_spend_apitest` MongoDB database and skip if MongoDB is not
available.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `redirect_uri_mismatch` | Register `http://localhost:8000/auth/google/callback` exactly in the same Google OAuth client used in `.env`. |
| `access_denied` for another Gmail account | Add that account to OAuth consent-screen **Test users**. |
| Gmail `accessNotConfigured` | Enable Gmail API in the Google Cloud project that owns the OAuth client, then wait a few minutes. |
| `Missing code verifier` | Restart the backend and begin a fresh Connect Gmail flow; do not reuse a callback URL. |
| Gemini model 404 | Use `GEMINI_MODEL=gemini-3.5-flash-lite`, then restart the backend. |
| Dashboard cannot reach backend | Check `http://localhost:8000/health`, then confirm the backend is running and `BACKEND_URL` is correct. |
| Docker build cannot pull base image | Confirm Docker Desktop is running and can reach Docker Hub, then retry `docker compose up --build`. |
