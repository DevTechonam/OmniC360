from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from omni.app import make_app
from omni.store import connect, digest, passwords

ORIGIN = 'http://localhost:5173'
PASSWORD = 'example-only-password-for-tests'
CUSTOMER = '/api/customers/acme'
QUEUE = f'{CUSTOMER}/tickets'
DEV = {'X-Environment': 'dev'}
PAYLOAD = {'source': 'chatbot', 'subject': 'Transfer never completes', 'description': 'Chat transfer timed out.',
           'priority': 'high', 'contact': 'person@example.test', 'external_reference': 'call-456'}


@pytest.fixture
def portal(tmp_path):
    path = tmp_path / 'test.sqlite3'
    with TestClient(make_app(path, origin=ORIGIN, secure_cookie=False, static_dir=tmp_path / 'no-build')) as client:
        with connect(path) as db:
            db.executemany('INSERT INTO customers VALUES (?,?)', [('acme', 'Acme'), ('other', 'Other')])
            db.executemany('INSERT INTO operators VALUES (?,?,?,?)', [
                (1, 'agent@example.test', 'Acme Operator', passwords.hash(PASSWORD)),
                (2, 'other@example.test', 'Other Operator', passwords.hash(PASSWORD)),
            ])
            db.executemany('INSERT INTO memberships VALUES (?,?)', [('acme', 1), ('other', 2)])
            db.executemany('INSERT INTO integration_keys VALUES (?,?,?,?,?)', [
                (digest(f'{customer}-{env}'), customer, env, 'test', 0) for customer in ('acme', 'other')
                for env in ('dev', 'qa', 'prod')
            ])
            db.execute('INSERT INTO integration_keys VALUES (?,?,?,?,?)', (digest('revoked'), 'acme', 'dev', 'old', 1))
        yield client, path


def intake(client, customer='acme', env='dev', event='event-456', payload=None, key=None):
    return client.post('/api/v1/tickets', json=PAYLOAD if payload is None else payload,
                       headers={'Authorization': f'Bearer {key or customer + "-" + env}', 'Idempotency-Key': event, 'X-Environment': env})


def login(client, email='agent@example.test', password=PASSWORD, origin=ORIGIN):
    return client.post('/api/session', headers={'Origin': origin}, json={'email': email, 'password': password})


def test_unauthenticated_requests(portal):
    client, _ = portal
    for method, url, body in [
        ('GET', '/api/session', None), ('DELETE', '/api/session', None), ('GET', f'{CUSTOMER}/operators', None),
        ('GET', QUEUE, None), ('GET', f'{QUEUE}/ESC-TEST', None),
        ('PATCH', f'{QUEUE}/ESC-TEST', {'status': 'closed'}), ('POST', f'{QUEUE}/ESC-TEST/notes', {'body': 'note'}),
        ('POST', '/api/v1/tickets', PAYLOAD),
    ]:
        assert client.request(method, url, headers=DEV, **({'json': body} if body else {})).status_code == 401
    assert intake(client, key='invalid').status_code == 401
    assert intake(client, key='revoked').status_code == 401
    assert intake(client, env='prod', key='acme-dev').status_code == 401


def test_intake_retry_and_scope(portal):
    client, _ = portal
    first = intake(client)
    assert first.status_code == 201
    assert first.headers['Cache-Control'] == 'no-store'
    replay = intake(client)
    assert replay.status_code == 200 and first.json() == replay.json()
    assert set(first.json()) == {'id', 'environment', 'created_at'}
    assert intake(client, payload={**PAYLOAD, 'subject': 'Different report'}).status_code == 409
    assert intake(client, payload={**PAYLOAD, 'customer_id': 'other'}).status_code == 422
    assert intake(client, env='qa', payload={**PAYLOAD, 'source': 'ivr'}).status_code == 201
    assert intake(client, env='prod').status_code == 201
    assert intake(client, customer='other').status_code == 201
    assert login(client).status_code == 200
    assert client.get('/api/customers/other/tickets', headers=DEV).status_code == 404
    assert client.get('/api/customers/other/operators').status_code == 404
    assert client.get(f'{QUEUE}/{first.json()["id"]}', headers={'X-Environment': 'prod'}).status_code == 404
    for env in ('dev', 'qa', 'prod'):
        assert client.get(QUEUE, headers={'X-Environment': env}).json()['total'] == 1


def test_concurrent_retry_creates_once(portal):
    client, _ = portal
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: intake(client, event='same-event'), range(6)))
    assert sorted(r.status_code for r in results) == [200] * 5 + [201]
    assert len({r.json()['id'] for r in results}) == 1


def test_lifecycle_and_audit(portal):
    client, _ = portal
    key = intake(client).json()['id']
    url = f'{QUEUE}/{key}'
    headers = {**DEV, 'Origin': ORIGIN}
    assert login(client, password='bad').status_code == 401
    assert login(client, origin='https://wrong.example.test').status_code == 403
    response = login(client)
    assert response.status_code == 200 and 'HttpOnly' in response.headers['Set-Cookie']
    assert client.get('/api/session').json()['customers'] == [{'id': 'acme', 'name': 'Acme'}]
    assert client.get(f'{QUEUE}?q=call-456&priority=high&status=open', headers=DEV).json()['total'] == 1
    assert client.get(f'{QUEUE}?q=missing', headers=DEV).json()['total'] == 0
    assert client.get(f'{QUEUE}?limit=1&offset=1', headers=DEV).json()['items'] == []
    assert client.patch(url, headers=DEV, json={'status': 'resolved'}).status_code == 403
    assert client.patch(url, headers=headers, json={'status': 'resolved', 'assignee_id': 2}).status_code == 422
    assert client.get(url, headers=DEV).json()['status'] == 'open'  # invalid assignment rolled back the whole change
    assert client.get(url, headers=DEV).json()['contact'] == PAYLOAD['contact']
    assert client.patch(url, headers=headers, json={'status': 'in_progress', 'assignee_id': 1}).status_code == 200
    assert client.post(f'{url}/notes', headers=headers, json={'body': '  '}).status_code == 422
    assert client.post(f'{url}/notes', headers=headers, json={'body': 'Spoke with support.'}).status_code == 201
    assert client.patch(url, headers=headers, json={'status': 'resolved', 'assignee_id': None}).status_code == 200
    detail = client.get(url, headers=DEV).json()
    assert detail['status'] == 'resolved' and detail['assignee_id'] is None
    assert [event['kind'] for event in detail['activity']] == ['assignment','status','note','assignment','status','created']
    assert detail['activity'][2]['body'] == 'Spoke with support.'
    assert client.get(QUEUE, headers=DEV).json()['counts'] == {'resolved': 1}
    assert client.delete('/api/session', headers=headers).status_code == 204
    assert client.get(url, headers=DEV).status_code == 401


def test_expired_sessions(portal):
    client, path = portal
    assert login(client).status_code == 200
    with connect(path) as db:
        db.execute('UPDATE sessions SET expires=1')
    assert client.get(QUEUE, headers=DEV).status_code == 401


def test_intake_credentials_cannot_read_or_mutate_operator_routes(portal):
    client, _ = portal
    key = intake(client).json()['id']
    headers = {**DEV, 'Authorization': 'Bearer acme-dev', 'Origin': ORIGIN}
    assert client.get(f'{QUEUE}/{key}', headers=headers).status_code == 401
    assert client.patch(f'{QUEUE}/{key}', headers=headers, json={'status': 'closed'}).status_code == 401
    assert client.post(f'{QUEUE}/{key}/notes', headers=headers, json={'body': 'Insert me'}).status_code == 401


def test_environment_header_required_and_validated(portal):
    client, _ = portal
    intake_headers = {'Authorization': 'Bearer acme-dev', 'Idempotency-Key': 'header-test'}
    assert client.post('/api/v1/tickets', headers=intake_headers, json=PAYLOAD).status_code == 422
    assert client.post('/api/v1/tickets', headers={**intake_headers, 'X-Environment': 'staging'}, json=PAYLOAD).status_code == 422
    assert client.post('/api/v1/dev/tickets', headers={**intake_headers, **DEV}, json=PAYLOAD).status_code == 404
    assert login(client).status_code == 200
    assert client.get(QUEUE).status_code == 422
    assert client.get(QUEUE, headers={'X-Environment': 'staging'}).status_code == 422
