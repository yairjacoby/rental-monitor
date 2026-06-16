"""
Seen Store — Supabase backed
Tracks listing IDs already sent to prevent duplicate alerts.
"""

import os
import logging

log = logging.getLogger(__name__)

_client = None

def get_client():
    global _client
    if _client is None:
        from supabase import create_client
        url = os.environ.get('SUPABASE_URL')
        key = os.environ.get('SUPABASE_KEY')
        if not url or not key:
            raise ValueError('SUPABASE_URL and SUPABASE_KEY must be set')
        _client = create_client(url, key)
    return _client


def init_db():
    """No-op — tables created via SQL migration in Supabase."""
    log.info('Supabase seen store ready')


def is_seen(listing_id: str) -> bool:
    try:
        result = get_client().table('seen').select('id').eq('id', listing_id).execute()
        return len(result.data) > 0
    except Exception as e:
        log.error(f'is_seen error: {e}')
        return False


def mark_seen(listing_id: str, source: str = 'unknown'):
    try:
        get_client().table('seen').upsert({
            'id': listing_id,
            'source': source
        }).execute()
    except Exception as e:
        log.error(f'mark_seen error: {e}')
