"""Secure the freshly initialized CWA admin; run only inside the CWA image."""
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat


def safe_path(path, *, required=False):
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError('Symlinked path refused')
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if required:
            raise ValueError('Required file is absent') from None
        return None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError('Expected a regular file with one link')
    return metadata


def bootstrap(database, credentials, *, generate_hash, check_hash):
    database, credentials = Path(database).absolute(), Path(credentials).absolute()
    safe_path(database, required=True)
    safe_path(credentials)
    created = None
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True)) as connection, connection:
            connection.execute('PRAGMA foreign_keys = ON')
            connection.execute('BEGIN IMMEDIATE')
            columns = {row[1]: row for row in connection.execute('PRAGMA table_info(user)')}
            table = connection.execute("SELECT type FROM sqlite_master WHERE name = 'user'").fetchone()
            if (table != ('table',) or not {'id', 'name', 'password', 'auto_send_enabled'} <= columns.keys()
                    or columns['id'][5] != 1):
                raise ValueError('Invalid CWA user schema')
            users = connection.execute('SELECT id, name, password FROM user').fetchall()
            admins = [user for user in users if user[0] == 1 and user[1] == 'admin']
            roles = dict(connection.execute('SELECT id, role FROM user')) if 'role' in columns else {}
            if (len(admins) != 1 or not isinstance(admins[0][2], str)
                    or any(user != admins[0] and not (
                        user[0] == 2 and user[1] == 'Guest' and user[2] == ''
                        and roles.get(user[0]) == (1 << 5)) for user in users)
                    or ('role' in columns and not (
                        isinstance(roles.get(1), int) and roles[1] & 1))):
                raise ValueError('Expected only the fresh admin and anonymous CWA Guest')
            admin = admins[0]
            if credentials.exists():
                fd = os.open(credentials, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd) as source:
                    metadata = os.fstat(source.fileno())
                    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                            or stat.S_IMODE(metadata.st_mode) != 0o600
                            or metadata.st_uid != os.geteuid() or metadata.st_gid != os.getegid()):
                        raise ValueError('Unsafe credential file')
                    login = json.load(source)
                current = connection.execute('SELECT password FROM user WHERE name = ?', ('admin',)).fetchone()
                if (set(login) != {'username', 'password'} or login['username'] != 'admin'
                        or not isinstance(login['password'], str)
                        or not current or not check_hash(current[0], login['password'])):
                    raise ValueError('Existing credentials do not match admin')
                connection.execute('UPDATE user SET auto_send_enabled = 0')
                return
            if not check_hash(admin[2], 'admin123'):
                raise ValueError('Admin is not freshly initialized')
            password = secrets.token_urlsafe(32)
            connection.execute('UPDATE user SET password = ? WHERE name = ?',
                               (generate_hash(password), 'admin'))
            connection.execute('UPDATE user SET auto_send_enabled = 0')
            fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            created = os.fstat(fd)
            with os.fdopen(fd, 'w') as output:
                os.fchmod(output.fileno(), 0o600)
                os.fchown(output.fileno(), os.geteuid(), os.getegid())
                json.dump({'username': 'admin', 'password': password}, output)
                output.flush()
                os.fsync(output.fileno())
    except BaseException:
        if created is not None:
            try:
                current = credentials.lstat()
                if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                    credentials.unlink()
            except FileNotFoundError:
                pass
        raise


def main():
    import sys
    try:
        from werkzeug.security import generate_password_hash, check_password_hash
        bootstrap(Path('/config/app.db'), Path('/config/admin-credentials.json'),
                  generate_hash=generate_password_hash, check_hash=check_password_hash)
    except Exception:
        sys.exit('bootstrap_admin: refused or failed; verify initialized CWA database and credential-file safety.')


if __name__ == '__main__':
    main()
