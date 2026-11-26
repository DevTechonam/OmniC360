# OmniC360 — customer escalations

A React and TypeScript agent console backed by FastAPI and SQLite. Chatbot and IVR services send escalations to an intake endpoint; operators can search the queue, review ticket details, assign ownership, change status, and add private notes. Changes are recorded in the ticket's activity history.

## Run locally

Requires Python 3.11+ and Node.js 22.12+. Run from the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
npm ci --prefix frontend
npm run build --prefix frontend

export PYTHONPATH=backend
export OMNI_DB="$PWD/omnic360.sqlite3"
export OMNI_ORIGIN=http://127.0.0.1:8000
export OMNI_SECURE_COOKIE=0 # local HTTP only

python -m omni.admin customer acme 'Acme Support'
python -m omni.admin operator agent@example.test 'Support Agent' # prompts for a password
python -m omni.admin member acme agent@example.test
python -m omni.admin key acme dev chatbot-v1                     # prints a key once
uvicorn omni.main:app --host 127.0.0.1 --port 8000
```

Open [the portal](http://127.0.0.1:8000/) or [the interactive API reference](http://127.0.0.1:8000/api/docs). There are no default accounts or keys. The CLI and server must use the same `OMNI_DB` path. The SQL schema is in `backend/omni/schema.sql` and loads automatically on startup.

For hot reload, start `npm run dev --prefix frontend`, set `OMNI_ORIGIN=http://localhost:5173` on the FastAPI process, and restart it with `--reload --reload-dir backend`. Open `http://localhost:5173` exactly (not `127.0.0.1:5173`) so the origin matches.

## Integration: create an escalation

Send a request from your chatbot or IVR server, **not** from browser code. Set `OMNI_INTEGRATION_KEY` in that server's secret store. For a one-off local test, use the Dev key generated above, then run:

```sh
curl -i http://127.0.0.1:8000/api/v1/tickets \
  -H "Authorization: Bearer ${OMNI_INTEGRATION_KEY:?set your Dev key}" \
  -H 'Content-Type: application/json' \
  -H 'X-Environment: dev' \
  -H 'Idempotency-Key: ivr-session-184:escalation-1' \
  --data '{"source":"ivr","subject":"Caller could not confirm order","description":"Caller asked for a live agent after two attempts.","priority":"high","external_reference":"ivr-session-184"}'
```

| Field | Contract |
|---|---|
| `X-Environment` header | Required on intake, ticket queue, detail, updates, and notes: `dev`, `qa`, or `prod`. No default. |
| `source` | Required: `chatbot` or `ivr` |
| `subject` | Required, 1–160 characters |
| `description` | Required, 1–8,000 characters |
| `priority` | `low`, `normal` (default), `high`, or `urgent` |
| `contact`, `external_reference` | Optional, 1–160 characters each |
| `Idempotency-Key` | Required, 1–128 characters (letters, digits, `_.:-`; starts with an alphanumeric). Use a stable, unique key per escalation, not per HTTP attempt. |

- `201` — created. The receipt includes `id`, `environment` and `created_at`.
- `200` — same key and normalized payload in the same customer/environment; returns the original receipt.
- `409` — same key but different payload. Do not automatically retry with a new key.
- `401` — missing, invalid, revoked or wrong-environment API key. `422` — invalid input.
- For transport failures or retryable server errors, retry with the same key and payload using backoff.

Keys are **create-only**. The customer is derived from the key, never accepted in the JSON body. Each customer has separate Dev, QA and Prod queues and integration keys. These are **logical partitions within a single deployment and database**, not physically isolated systems. Workspace membership grants an operator access to all three environments for that customer. Agent operations require a session; edits require the configured origin. See `/api/openapi.json` for the generated API contract.

## Operator and key administration

- Grant access with `python -m omni.admin member <customer> <operator-email>`.
- Generate a separate secret for each integration/customer/environment, e.g. `python -m omni.admin key acme qa ivr-v1`.
- To rotate, issue a new key with a new label, update and test the integration, then run `python -m omni.admin revoke-key acme qa ivr-v1`. Revoked labels remain reserved.
- Operators may be assigned multiple customer memberships. There is no public sign-up, SSO, admin UI, or automatic ingest of call recordings in this version.

## Before running with real customer data

Build the frontend, serve FastAPI behind an HTTPS reverse proxy, set the exact HTTPS `OMNI_ORIGIN`, and leave `OMNI_SECURE_COOKIE` at its default `1`. Use a persistent local volume, restrict its permissions, and use SQLite-aware backups. Put rate limiting on login and intake and enforce request-size limits at the reverse proxy. Keep secrets out of the repo and customer data out of request logs. Define retention, redaction, and deletion procedures before collecting PII; send short issue summaries rather than raw recordings or transcripts. Use separate deployments if you need physical isolation, and revisit the database choice before multi-instance production usage. This repository does not deploy the app.

## Verify

```sh
PYTHONPATH=backend python -m pytest -q backend/tests
npm ci --prefix frontend
npm run build --prefix frontend
```

GitHub Actions runs both checks on pushes and pull requests. The test suite checks authentication, tenant and environment isolation, concurrent retries, assignment validation, the audit trail, and session expiry.
