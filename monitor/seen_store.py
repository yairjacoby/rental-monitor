import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'seen_listings.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS seen (
            id TEXT PRIMARY KEY,
            source TEXT,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_seen(listing_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT 1 FROM seen WHERE id = ?', (listing_id,)).fetchone()
    conn.close()
    return row is not None

def mark_seen(listing_id: str, source: str = 'facebook'):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('INSERT OR IGNORE INTO seen (id, source) VALUES (?, ?)', (listing_id, source))
    conn.commit()
    conn.close()
