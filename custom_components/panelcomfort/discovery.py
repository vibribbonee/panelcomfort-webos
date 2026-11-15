from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import network as ha_network

from .const import CONF_DEVICE_ID, CONF_HOST, CONF_PORT, DEFAULT_PORT, DISCOVERY_PATH

_LOGGER = logging.getLogger(__name__)
_REDISCOVERY_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_REDISCOVERY_CACHE_SECONDS = 45.0


def _base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


async def async_probe_host(
    hass: HomeAssistant, host: str, port: int, timeout_seconds: float = 1.2
) -> dict[str, Any] | None:
    """Return stable, non-secret discovery metadata from a PanelComfort TV."""
    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=timeout_seconds)
    try:
        async with session.get(
            _base_url(host, port) + DISCOVERY_PATH,
            timeout=timeout,
            headers={"Cache-Control": "no-cache"},
        ) as response:
            if response.status != 200:
                return None
            payload = await response.json(content_type=None)
        if (
            isinstance(payload, dict)
            and payload.get("ok") is True
            and payload.get("domain") == "panelcomfort"
            and isinstance(payload.get("device_id"), str)
            and payload["device_id"]
        ):
            return {
                CONF_HOST: host,
                CONF_PORT: int(payload.get("port", port)),
                CONF_DEVICE_ID: payload["device_id"],
            }
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None
    return None


async def async_device_from_ssdp(hass: HomeAssistant, discovery_info: Any) -> dict[str, Any] | None:
    """Resolve an SSDP discovery event to PanelComfort's stable identity."""
    location = getattr(discovery_info, "ssdp_location", None)
    if not location:
        headers = getattr(discovery_info, "ssdp_headers", {}) or {}
        location = headers.get("location") or headers.get("LOCATION")
    if not location:
        return None
    parsed = urlsplit(str(location))
    if parsed.scheme != "http" or not parsed.hostname:
        return None
    return await async_probe_host(hass, parsed.hostname, parsed.port or DEFAULT_PORT)


async def _candidate_hosts(hass: HomeAssistant) -> list[str]:
    """Return bounded local IPv4 ranges for the fallback discovery scan."""
    try:
        adapters = await ha_network.async_get_adapters(hass)
    except (RuntimeError, OSError, AttributeError):
        _LOGGER.debug("Could not query Home Assistant network adapters", exc_info=True)
        return []
    networks: dict[str, ipaddress.IPv4Network] = {}
    for adapter in adapters:
        if adapter.get("enabled") is False:
            continue
        for item in adapter.get("ipv4", []):
            address = item.get("address")
            prefix = item.get("network_prefix", 24)
            if not address:
                continue
            try:
                interface = ipaddress.ip_interface(f"{address}/{int(prefix)}")
                if interface.ip.is_loopback or interface.ip.is_link_local or interface.ip.is_multicast or interface.ip.is_unspecified:
                    continue
                network = interface.network
                # A bridged HA VM can share a /23 or /22 LAN with the TV.
                # Narrowing those networks to HA's own /24 silently misses TVs
                # whose DHCP lease lands in the other half of the LAN. Keep the
                # scan bounded, but cover up to 1024 addresses before falling
                # back to the interface's /24 on unusually large networks.
                if network.num_addresses > 1024:
                    network = ipaddress.ip_network(f"{interface.ip}/24", strict=False)
                if network.num_addresses <= 1024:
                    networks[str(network)] = network
            except (ValueError, TypeError):
                continue
    hosts: set[str] = set()
    for network in networks.values():
        hosts.update(str(host) for host in network.hosts())
    _LOGGER.debug(
        "PanelComfort discovery will scan %s hosts across %s",
        len(hosts),
        ", ".join(sorted(networks)) or "no eligible IPv4 subnets",
    )
    return sorted(hosts)


async def async_discover_devices(hass: HomeAssistant, port: int = DEFAULT_PORT) -> list[dict[str, Any]]:
    """Find PanelComfort TVs on the local subnets; no secret token is needed."""
    hosts = await _candidate_hosts(hass)
    if not hosts:
        return []
    session = async_get_clientsession(hass)
    semaphore = asyncio.Semaphore(48)
    timeout = aiohttp.ClientTimeout(total=1.1, connect=0.7)

    async def probe(host: str) -> dict[str, Any] | None:
        async with semaphore:
            try:
                async with session.get(
                    _base_url(host, port) + DISCOVERY_PATH,
                    timeout=timeout,
                    headers={"Cache-Control": "no-cache"},
                ) as response:
                    if response.status != 200:
                        return None
                    payload = await response.json(content_type=None)
                if (
                    isinstance(payload, dict)
                    and payload.get("ok") is True
                    and payload.get("domain") == "panelcomfort"
                    and isinstance(payload.get("device_id"), str)
                    and payload["device_id"]
                ):
                    return {
                        CONF_HOST: host,
                        CONF_PORT: int(payload.get("port", port)),
                        CONF_DEVICE_ID: payload["device_id"],
                    }
            except (aiohttp.ClientError, TimeoutError, ValueError):
                return None
            return None

    results = await asyncio.gather(*(probe(host) for host in hosts), return_exceptions=True)
    by_id: dict[str, dict[str, Any]] = {}
    for result in results:
        if isinstance(result, dict):
            by_id.setdefault(result[CONF_DEVICE_ID], result)
    return list(by_id.values())


async def async_find_device(
    hass: HomeAssistant,
    port: int,
    expected_device_id: str | None,
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    """Find a TV again after DHCP changes, with a shared cooldown across entities.

    The switch, sensors and number entity all poll independently in Home Assistant.
    Cache both a successful result and a miss so one offline TV does not trigger four
    subnet scans every polling cycle. Explicit control actions can bypass the cache.
    """
    key = f"{port}:{expected_device_id or '*'}"
    now = time.monotonic()
    cached = _REDISCOVERY_CACHE.get(key)
    if not force and cached and now - cached[0] < _REDISCOVERY_CACHE_SECONDS:
        return cached[1]

    devices = await async_discover_devices(hass, port)
    found = None
    for device in devices:
        if (
            not expected_device_id
            or expected_device_id.startswith("legacy-")
            or device[CONF_DEVICE_ID] == expected_device_id
        ):
            found = device
            break
    _REDISCOVERY_CACHE[key] = (time.monotonic(), found)
    return found


def legacy_identity(token: str) -> str:
    """Stable fallback identity for upgrading old entries if the TV is offline."""
    import hashlib
    return "legacy-" + hashlib.sha256(token.encode()).hexdigest()[:24]
