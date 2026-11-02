"""List local GUI chat identifiers read-only, without reading chat content or credentials."""
import argparse
import json
from pathlib import Path
import sqlite3
from contextlib import closing


def list_chats(database, limit=20):
    path = Path(database).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        required = {'task_id', 'title', 'workspace_path', 'deleted', 'archived', 'updated_at'}
        columns = {row[1] for row in connection.execute('PRAGMA table_info(tasks)')}
        if not required <= columns:
            raise ValueError('Unsupported local task-index schema; no changes made')
        rows = connection.execute('SELECT task_id, title, workspace_path FROM tasks '
                                  'WHERE deleted=0 AND archived=0 ORDER BY updated_at DESC LIMIT ?', (limit,))
        return [{'session_id': session, 'title': title, 'workspace': workspace}
                for session, title, workspace in rows if session.startswith('sess_')]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zcode-home', type=Path, default=Path.home() / '.zcode')
    parser.add_argument('--limit', type=int, choices=range(1, 51), default=20, metavar='1..50')
    args = parser.parse_args()
    try:
        print(json.dumps(list_chats(args.zcode_home / 'v2/tasks-index.sqlite', args.limit), indent=2))
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, str(error) + '\n')
