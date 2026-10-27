"""Read-only Render release verification. Never authenticates or uploads data."""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import httpx

ENDPOINTS = {
    'web': 'https://flexmap-rehab-web-parmankaiwan.onrender.com/api/version',
    'api': 'https://flexmap-rehab-api-parmankaiwan.onrender.com/version',
}


def probe(item: tuple[str, str], expected: str | None) -> dict:
    name, url = item
    try:
        response = httpx.get(url, timeout=25, headers={'Cache-Control': 'no-cache'})
        body = response.json() if 'application/json' in response.headers.get('content-type', '') else {}
        return {'service': name, 'http_status': response.status_code, 'release': body.get('release'),
                'commit': body.get('commit'), 'verified': response.status_code == 200 and bool(expected) and body.get('commit') == expected}
    except (httpx.HTTPError, ValueError) as exc:
        return {'service': name, 'http_status': None, 'error_type': type(exc).__name__, 'verified': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-sha')
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: probe(item, args.expected_sha), ENDPOINTS.items()))
    print(json.dumps({'results': results, 'all_verified': all(item['verified'] for item in results)}, indent=2))
    return 0 if all(item['verified'] for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
