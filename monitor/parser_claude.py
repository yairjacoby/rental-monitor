"""
Claude API Parser
Parses unstructured Hebrew Facebook posts and extracts structured rental listing data.
Filters against config parameters and returns only matching listings.
"""

import os
import json
import logging
from typing import Optional
import anthropic

log = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

SYSTEM_PROMPT = """You are a Hebrew real estate listing parser for the Israeli rental market.
You receive raw text from Israeli Facebook rental groups and extract structured data.
Always respond with valid JSON only — no explanation, no markdown, no extra text.

Extract these fields:
- price (integer, monthly rent in NIS, null if not found)
- rooms (float, number of rooms, null if not found — 4.5 is valid)
- city (string, city name in Hebrew, null if not found)
- neighborhood (string, neighborhood name in Hebrew, null if not found)
- parking (boolean, true if parking mentioned, false if explicitly no parking, null if not mentioned)
- safe_room (boolean, true if ממד/ממ״ד/מרחב מוגן mentioned, false if explicitly none, null if not mentioned)
- broker (boolean, true if broker/תיווך involved, false if ללא תיווך, null if not mentioned)
- entry_date (string, when available in ISO format YYYY-MM-DD, null if not found)
- is_rental (boolean, true if this is a rental listing, false if it is a sale, question, or unrelated post)
- summary (string, one sentence summary in English)

Currency notes: ש״ח, שח, שקל, שקלים, ₪, NIS all mean Israeli Shekel.
Room aliases: חדרים, חד׳, חד' all mean rooms.
Parking aliases: חניה, חנייה, חנ׳
Safe room aliases: ממד, ממ״ד, מרחב מוגן"""


def parse_post(post: dict, config: dict) -> Optional[dict]:
    """
    Parse a single Facebook post with Claude.
    Returns structured listing dict if it matches config filters, else None.
    """
    text = post.get('text', '')
    if not text:
        return None

    try:
        message = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': text}]
        )
        raw = message.content[0].text.strip()
        raw = raw.replace('```json', '').replace('```', '').strip()
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning(f'JSON parse error for post {post.get("id")}: {e}')
        return None
    except Exception as e:
        log.error(f'Claude API error for post {post.get("id")}: {e}')
        return None

    # Must be a rental listing
    if not parsed.get('is_rental'):
        log.debug(f'Post {post.get("id")} is not a rental listing — skipping')
        return None

    # Apply config filters
    searches = config.get('searches', [])
    filters = config.get('filters', {})
    rooms_min = filters.get('rooms_min', 1)
    must_have = filters.get('must_have', {})
    broker_config = config.get('broker', {})
    exclude_broker = broker_config.get('exclude_broker', False)

    # Rooms filter
    rooms = parsed.get('rooms')
    if rooms is not None and rooms < rooms_min:
        log.debug(f'Post {post.get("id")} filtered out — rooms {rooms} < {rooms_min}')
        return None

    # Must-have filters
    if must_have.get('parking') and parsed.get('parking') is False:
        log.debug(f'Post {post.get("id")} filtered out — no parking')
        return None

    if must_have.get('safe_room') and parsed.get('safe_room') is False:
        log.debug(f'Post {post.get("id")} filtered out — no safe room')
        return None

    # Broker filter
    if exclude_broker and parsed.get('broker') is True:
        log.debug(f'Post {post.get("id")} filtered out — broker involved')
        return None

    # Price + city/neighborhood filter — match against any configured search
    listing_city = (parsed.get('city') or '').strip()
    listing_neighborhood = (parsed.get('neighborhood') or '').strip()
    listing_price = parsed.get('price')

    matched_search = False
    for search in searches:
        # Price check
        max_price = search.get('max_price')
        if max_price and listing_price and listing_price > max_price:
            continue

        # City check — match against city + aliases
        city_aliases = [search.get('city', '')] + search.get('city_aliases', [])
        city_aliases_lower = [c.lower() for c in city_aliases if c]
        city_match = (
            not listing_city or
            any(alias in listing_city.lower() for alias in city_aliases_lower) or
            any(listing_city.lower() in alias for alias in city_aliases_lower)
        )
        if not city_match:
            continue

        # Neighborhood check
        neighborhoods = [n.lower() for n in search.get('neighborhoods', [])]
        neighborhood_match = (
            not neighborhoods or
            not listing_neighborhood or
            any(n in listing_neighborhood.lower() for n in neighborhoods) or
            any(listing_neighborhood.lower() in n for n in neighborhoods)
        )
        if not neighborhood_match:
            continue

        matched_search = True
        break

    if not matched_search:
        log.debug(f'Post {post.get("id")} did not match any search config')
        return None

    return {
        **post,
        'parsed': parsed,
    }


def parse_listings(posts: list[dict], config: dict) -> list:
    """Parse and filter a list of raw posts. Returns matched listings only."""
    matched = []
    for post in posts:
        result = parse_post(post, config)
        if result:
            matched.append(result)
            log.info(f'Match: {result["parsed"].get("summary")}')
    return matched
