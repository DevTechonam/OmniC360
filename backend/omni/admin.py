import argparse
import getpass
import re
import secrets
import sqlite3
from .store import connect, database_path, digest, initialize, passwords


def main():
    parser = argparse.ArgumentParser(description='Provision OmniC360 customers, operators and integrations')
    sub = parser.add_subparsers(dest='action', required=True)
    customer = sub.add_parser('customer')
    customer.add_argument('id')
    customer.add_argument('name')
    operator = sub.add_parser('operator')
    operator.add_argument('email')
    operator.add_argument('name')
    member = sub.add_parser('member')
    member.add_argument('customer')
    member.add_argument('email')
    for cmd in ('key', 'revoke-key'):
        key = sub.add_parser(cmd)
        key.add_argument('customer')
        key.add_argument('env', choices=['dev','qa','prod'])
        key.add_argument('label')
    args = parser.parse_args()
    path = database_path()
    initialize(path)
    try:
        with connect(path) as db:
            match args.action:
                case 'customer':
                    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,62}', args.id):
                        parser.error('Use a lowercase slug for the customer ID')
                    db.execute('INSERT INTO customers VALUES (?,?)', (args.id,args.name))
                case 'operator':
                    password = getpass.getpass('Operator password: ')
                    if not 12 <= len(password) <= 256:
                        parser.error('Password must contain 12–256 characters')
                    if password != getpass.getpass('Confirm password: '):
                        parser.error('Passwords do not match')
                    db.execute('INSERT INTO operators(email,name,password_hash) VALUES (?,?,?)',
                               (args.email.strip().casefold(), args.name, passwords.hash(password)))
                case 'member':
                    row = db.execute('SELECT id FROM operators WHERE email=?', (args.email.strip().casefold(),)).fetchone()
                    if not row:
                        parser.error('Operator not found')
                    db.execute('INSERT OR IGNORE INTO memberships VALUES (?,?)', (args.customer, row['id']))
                case 'key':
                    token = f'omni_{args.env}_{secrets.token_urlsafe(32)}'
                    db.execute('''INSERT INTO integration_keys(token_hash,customer_id,environment,label) VALUES (?,?,?,?)''',
                               (digest(token), args.customer, args.env, args.label))
                case 'revoke-key':
                    row = db.execute('UPDATE integration_keys SET revoked=1 WHERE customer_id=? AND environment=? AND label=?',
                                     (args.customer,args.env,args.label))
                    if not row.rowcount:
                        parser.error('Key not found')
    except sqlite3.IntegrityError as exc:
        parser.exit(1, f'Provisioning failed: {exc}\n')
    if args.action == 'key':
        print(token)
    else:
        print('Done')


if __name__ == '__main__':
    main()
