from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend import lifecycle_api


def request(host='127.0.0.1'):
    return Request({'type': 'http', 'client': (host, 1234), 'method': 'POST', 'path': '/'})


def test_independent_capability_discovery_is_not_http_error(monkeypatch):
    monkeypatch.delenv('FLEXMAP_LOCAL_LIFECYCLE_ENABLED', raising=False)
    value = lifecycle_api.lifecycle_status(request())
    assert value['available'] is False
    assert not any(value['controls'].values())


@pytest.mark.parametrize('enabled,host,expected', [('false','127.0.0.1',409), ('true','192.0.2.10',403), ('true','127.0.0.1',503)])
def test_rejected_stop_never_interrupts_recordings(monkeypatch, enabled, host, expected):
    monkeypatch.setenv('FLEXMAP_LOCAL_LIFECYCLE_ENABLED', enabled)
    monkeypatch.delenv('FLEXMAP_LIFECYCLE_TOKEN', raising=False)
    prepare = Mock()
    monkeypatch.setattr(lifecycle_api, 'prepare_for_shutdown', prepare)
    with pytest.raises(HTTPException) as exc:
        lifecycle_api.lifecycle_stop(request(host))
    assert exc.value.status_code == expected
    prepare.assert_not_called()
