"""The fallback scan finds a TV that moved to a new address."""
from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockModule, mock_integration

from custom_components.panelcomfort import discovery

ADAPTERS = [{
    "name": "eth0", "enabled": True, "auto": True, "default": True,
    "ipv4": [{"address": "192.168.0.190", "network_prefix": 24}], "ipv6": [],
}]


async def test_scan_covers_home_assistants_lan(hass):
    mock_integration(hass, MockModule("ssdp"))
    with patch.object(discovery.ha_network, "async_get_adapters", return_value=ADAPTERS) as get:
        hosts = await discovery._candidate_hosts(hass)
    get.assert_awaited_once()
    assert "192.168.0.186" in hosts and len(hosts) == 254


async def test_moved_tv_is_found_by_its_device_id(hass, aioclient_mock):
    discovery._REDISCOVERY_CACHE.clear()
    aioclient_mock.get(
        "http://192.168.0.186:8765/cgi-bin/panelcomfort-discovery.cgi",
        json={"ok": True, "domain": "panelcomfort", "device_id": "tv-1", "port": 8765},
    )
    with patch.object(discovery.ha_network, "async_get_adapters", return_value=ADAPTERS), \
            patch.object(discovery.asyncio, "Semaphore", return_value=__import__("asyncio").Semaphore(300)):
        found = await discovery.async_find_device(hass, 8765, "tv-1", force=True)
    assert found == {"host": "192.168.0.186", "port": 8765, "device_id": "tv-1"}
