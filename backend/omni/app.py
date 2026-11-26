import hmac
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .models import AddNote, Env, Intake, Login, Priority, Receipt, Status, UpdateTicket
from .store import connect, database_path, digest, initialize, now, passwords

EnvironmentHeader = Annotated[Env, Header(alias='X-Environment', description='Ticket environment: dev, qa, or prod')]

COOKIE = 'omni_session'
SESSION_SECONDS = 8 * 60 * 60
BEARER = HTTPBearer(auto_error=False)
TICKET_FIELDS = 't.id,t.subject,t.priority,t.status,t.source,t.assignee_id,t.created_at,t.updated_at,o.name AS assignee_name'


def make_app(path=None, origin=None, secure_cookie=None, static_dir=None):
    path = path or database_path()
    origin = (origin or os.getenv('OMNI_ORIGIN', 'http://localhost:5173')).rstrip('/')
    if secure_cookie is None:
        secure_cookie = os.getenv('OMNI_SECURE_COOKIE', '1') != '0'
    dummy_hash = passwords.hash(secrets.token_hex(16))

    @asynccontextmanager
    async def lifespan(_):
        initialize(path)
        yield

    app = FastAPI(title='OmniC360 Escalation API', version='1.0.0', docs_url='/api/docs',
                  redoc_url=None, openapi_url='/api/openapi.json', lifespan=lifespan)

    @app.middleware('http')
    async def protect_api(request: Request, call_next):
        url = request.url.path
        if not (url == '/api' or url.startswith('/api/')):
            return await call_next(request)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_request, exc):
        return JSONResponse(status_code=422, content={'detail': [
            {'loc': error['loc'], 'msg': error['msg'], 'type': error['type']} for error in exc.errors()
        ]}, headers={'Cache-Control': 'no-store'})

    def same_origin(request: Request):
        caller = request.headers.get('origin')
        if not caller and (referer := request.headers.get('referer')):
            ref = urlsplit(referer)
            caller = f'{ref.scheme}://{ref.netloc}'
        if caller != origin:
            raise HTTPException(403, 'Request origin not allowed')

    def bearer_token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(BEARER)]):
        if not credentials or len(credentials.credentials) > 128:
            raise HTTPException(401, 'Invalid integration key', headers={'WWW-Authenticate': 'Bearer'})
        return credentials.credentials

    def identity(request: Request):
        token = request.cookies.get(COOKIE, '')
        if not token or len(token) > 128:
            raise HTTPException(401, 'Sign in required')
        with connect(path) as db:
            actor = db.execute('''SELECT o.id,o.email,o.name FROM sessions s JOIN operators o ON o.id=s.operator_id
                WHERE s.token_hash=? AND s.expires>?''', (digest(token), int(time.time()))).fetchone()
        if actor is None:
            raise HTTPException(401, 'Sign in required')
        return actor

    def member(customer: str, operator: Annotated[dict, Depends(identity)]):
        with connect(path) as db:
            found = db.execute('SELECT 1 FROM memberships WHERE customer_id=? AND operator_id=?',
                               (customer, operator['id'])).fetchone()
        if not found:
            raise HTTPException(404, 'Customer not found')
        return operator

    def ticket(db, customer, env, ticket_id):
        row = db.execute(f'''SELECT {TICKET_FIELDS},t.description,t.contact,t.external_reference,t.environment
            FROM tickets t LEFT JOIN operators o ON t.assignee_id=o.id
            WHERE t.customer_id=? AND t.environment=? AND t.id=?''', (customer, env, ticket_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Ticket not found')
        return dict(row)

    def add_activity(db, ticket_id, actor, kind, body, timestamp):
        db.execute('INSERT INTO activity(ticket_id,operator_id,kind,body,created_at) VALUES (?,?,?,?,?)',
                   (ticket_id, actor, kind, body, timestamp))

    @app.get('/api/health')
    def health():
        with connect(path) as db:
            db.execute('SELECT 1 FROM customers LIMIT 1')
        return {'status': 'ok'}

    @app.post('/api/session', dependencies=[Depends(same_origin)])
    def login(payload: Login, request: Request, response: Response):
        with connect(path) as db:
            actor = db.execute('SELECT * FROM operators WHERE email=?', (payload.email.casefold(),)).fetchone()
            try:
                passwords.verify(actor['password_hash'] if actor else dummy_hash, payload.password)
            except VerificationError:
                raise HTTPException(401, 'Invalid email or password') from None
            if not actor:
                raise HTTPException(401, 'Invalid email or password')
            token = secrets.token_urlsafe(32)
            expires = int(time.time()) + SESSION_SECONDS
            old_token = request.cookies.get(COOKIE)
            if old_token:
                db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(old_token),))
            db.execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), actor['id'], expires))
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            samesite='strict', secure=secure_cookie)
        return {'id': actor['id'], 'name': actor['name']}

    @app.delete('/api/session', status_code=204, dependencies=[Depends(identity), Depends(same_origin)])
    def logout(request: Request, response: Response):
        with connect(path) as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(request.cookies[COOKIE]),))
        response.delete_cookie(COOKIE, httponly=True, samesite='strict', secure=secure_cookie)

    @app.get('/api/session')
    def session(actor: Annotated[dict, Depends(identity)]):
        with connect(path) as db:
            customers = db.execute('''SELECT c.id,c.name FROM customers c JOIN memberships m ON m.customer_id=c.id
                WHERE m.operator_id=? ORDER BY c.name,c.id''', (actor['id'],)).fetchall()
        return {'operator': dict(actor), 'customers': [dict(row) for row in customers]}

    @app.post('/api/v1/tickets', status_code=201, response_model=Receipt,
              responses={200: {'model': Receipt, 'description': 'Idempotent replay'},
                         401: {'description': 'Missing, revoked or wrong-environment key'},
                         409: {'description': 'Retry key already used with a different payload'}})
    def create(env: EnvironmentHeader, payload: Intake, response: Response,
               token: Annotated[str, Depends(bearer_token)],
               retry: Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=128,
                                            pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:\-]*$')]):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            key = db.execute('''SELECT customer_id FROM integration_keys
                WHERE token_hash=? AND environment=? AND revoked=0''', (digest(token), env)).fetchone()
            if not key:
                raise HTTPException(401, 'Invalid integration key', headers={'WWW-Authenticate': 'Bearer'})
            customer = key['customer_id']
            hashed = digest(payload.model_dump_json())
            row = db.execute('''SELECT id,environment,created_at,payload_hash FROM tickets
                 WHERE customer_id=? AND environment=? AND idempotency_key=?''', (customer, env, retry)).fetchone()
            if row:
                if not hmac.compare_digest(row['payload_hash'], hashed):
                    raise HTTPException(409, 'Idempotency key already used with a different payload')
                response.status_code = 200
                return {k: row[k] for k in ('id', 'environment', 'created_at')}
            ticket_id = 'ESC-' + secrets.token_hex(8).upper()
            timestamp = now()
            db.execute('''INSERT INTO tickets(id,customer_id,environment,idempotency_key,payload_hash,source,subject,
                description,contact,external_reference,priority,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (ticket_id, customer, env, retry, hashed, payload.source, payload.subject, payload.description,
                 payload.contact, payload.external_reference, payload.priority, timestamp, timestamp))
            add_activity(db, ticket_id, None, 'created', f'Escalation received via {"IVR" if payload.source == "ivr" else "chatbot"}.', timestamp)
        return {'id': ticket_id, 'environment': env, 'created_at': timestamp}

    @app.get('/api/customers/{customer}/operators')
    def operators(customer: str, _actor: Annotated[dict, Depends(member)]):
        with connect(path) as db:
            return [dict(row) for row in db.execute('''SELECT o.id,o.name FROM operators o JOIN memberships m
                ON m.operator_id=o.id WHERE m.customer_id=? ORDER BY o.name,o.id''', (customer,))]

    @app.get('/api/customers/{customer}/tickets')
    def queue(customer: str, env: EnvironmentHeader, _actor: Annotated[dict, Depends(member)],
              q: Annotated[str, Query(max_length=160)] = '', status: Status | None = None,
              priority: Priority | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 25,
              offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0):
        conditions, args = ['t.customer_id=?', 't.environment=?'], [customer, env]
        if q.strip():
            conditions.append('''(instr(lower(t.id), lower(?))>0 OR instr(lower(t.subject), lower(?))>0
                OR instr(lower(COALESCE(t.external_reference,'')), lower(?))>0)''')
            args.extend([q.strip()] * 3)
        if status:
            conditions.append('t.status=?')
            args.append(status)
        if priority:
            conditions.append('t.priority=?')
            args.append(priority)
        where = ' AND '.join(conditions)
        with connect(path) as db:
            db.execute('BEGIN')
            total = db.execute(f'SELECT COUNT(*) FROM tickets t WHERE {where}', args).fetchone()[0]
            counts = dict(db.execute('''SELECT status,COUNT(*) FROM tickets WHERE customer_id=? AND environment=?
                  GROUP BY status''', (customer, env)).fetchall())
            rows = db.execute(f'''SELECT {TICKET_FIELDS} FROM tickets t LEFT JOIN operators o ON t.assignee_id=o.id
                  WHERE {where} ORDER BY t.updated_at DESC,t.id LIMIT ? OFFSET ?''', (*args, limit, offset)).fetchall()
        return {'items': [dict(row) for row in rows], 'total': total, 'counts': counts}

    @app.get('/api/customers/{customer}/tickets/{ticket_id}')
    def detail(customer: str, env: EnvironmentHeader, ticket_id: str, _actor: Annotated[dict, Depends(member)]):
        with connect(path) as db:
            db.execute('BEGIN')
            data = ticket(db, customer, env, ticket_id)
            rows = db.execute('''SELECT a.id,a.kind,a.body,a.created_at,o.name AS actor FROM activity a
                  LEFT JOIN operators o ON o.id=a.operator_id WHERE a.ticket_id=? ORDER BY a.id DESC''', (ticket_id,))
            data['activity'] = [dict(row) for row in rows]
        return data

    @app.patch('/api/customers/{customer}/tickets/{ticket_id}')
    def update(customer: str, env: EnvironmentHeader, ticket_id: str, payload: UpdateTicket, actor: Annotated[dict, Depends(member)], _origin: Annotated[None, Depends(same_origin)]):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            current = ticket(db, customer, env, ticket_id)
            timestamp = now()
            if payload.status and payload.status != current['status']:
                db.execute('UPDATE tickets SET status=?,updated_at=? WHERE id=?', (payload.status, timestamp, ticket_id))
                label = lambda text: text.replace('_', ' ')
                add_activity(db, ticket_id, actor['id'], 'status',
                             f"Changed status from {label(current['status'])} to {label(payload.status)}.", timestamp)
            if 'assignee_id' in payload.model_fields_set and payload.assignee_id != current['assignee_id']:
                name = None
                if payload.assignee_id is not None:
                    row = db.execute('''SELECT o.name FROM operators o JOIN memberships m ON o.id=m.operator_id
                        WHERE o.id=? AND m.customer_id=?''', (payload.assignee_id, customer)).fetchone()
                    if not row:
                        raise HTTPException(422, 'Assignee is not a member of this customer')
                    name = row['name']
                db.execute('UPDATE tickets SET assignee_id=?,updated_at=? WHERE id=?', (payload.assignee_id, timestamp, ticket_id))
                add_activity(db, ticket_id, actor['id'], 'assignment',
                             f'Assigned to {name}.' if name else 'Removed assignment.', timestamp)
            return ticket(db, customer, env, ticket_id)

    @app.post('/api/customers/{customer}/tickets/{ticket_id}/notes', status_code=201)
    def note(customer: str, env: EnvironmentHeader, ticket_id: str, payload: AddNote, actor: Annotated[dict, Depends(member)], _origin: Annotated[None, Depends(same_origin)]):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            ticket(db, customer, env, ticket_id)
            timestamp = now()
            add_activity(db, ticket_id, actor['id'], 'note', payload.body, timestamp)
            db.execute('UPDATE tickets SET updated_at=? WHERE id=?', (timestamp, ticket_id))
        return {'created_at': timestamp}

    build = Path(static_dir) if static_dir else Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    if build.is_dir():
        @app.api_route('/api/{unmatched:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'], include_in_schema=False)
        def unknown_api(unmatched: str):
            raise HTTPException(404, 'API route not found')

        app.mount('/', StaticFiles(directory=build, html=True), name='portal')
    return app
