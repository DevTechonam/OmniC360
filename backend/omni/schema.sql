PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS customers (
 id TEXT PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operators (
 id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
 customer_id TEXT NOT NULL REFERENCES customers(id), operator_id INTEGER NOT NULL REFERENCES operators(id),
 PRIMARY KEY(customer_id, operator_id)
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, operator_id INTEGER NOT NULL REFERENCES operators(id), expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS integration_keys (
 token_hash TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
 environment TEXT NOT NULL CHECK(environment IN ('dev','qa','prod')), label TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
 UNIQUE(customer_id, environment, label)
);
CREATE TABLE IF NOT EXISTS tickets (
 id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
 environment TEXT NOT NULL CHECK(environment IN ('dev','qa','prod')),
 idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('chatbot','ivr')),
 subject TEXT NOT NULL, description TEXT NOT NULL, contact TEXT, external_reference TEXT,
 priority TEXT NOT NULL CHECK(priority IN ('low','normal','high','urgent')),
 status TEXT NOT NULL CHECK(status IN ('open','in_progress','resolved','closed')) DEFAULT 'open',
 assignee_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(customer_id, assignee_id) REFERENCES memberships(customer_id,operator_id),
 UNIQUE(customer_id, environment, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ticket_queue ON tickets(customer_id,environment,updated_at DESC,id);
CREATE TABLE IF NOT EXISTS activity (
 id INTEGER PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
 operator_id INTEGER REFERENCES operators(id), kind TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS activity_ticket ON activity(ticket_id,id);
