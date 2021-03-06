"""Support for the Philips Hue system."""
import logging

from aiohue.util import normalize_bridge_id

from homeassistant import config_entries, core
from homeassistant.components import persistent_notification
from homeassistant.helpers import device_registry as dr

from .bridge import HueBridge
from .const import (
    CONF_ALLOW_HUE_GROUPS,
    CONF_ALLOW_UNREACHABLE,
    DEFAULT_ALLOW_HUE_GROUPS,
    DEFAULT_ALLOW_UNREACHABLE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass, config):
    """Set up the Hue platform."""
    hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    """Set up a bridge from a config entry."""

    # Migrate allow_unreachable from config entry data to config entry options
    if (
        CONF_ALLOW_UNREACHABLE not in entry.options
        and CONF_ALLOW_UNREACHABLE in entry.data
        and entry.data[CONF_ALLOW_UNREACHABLE] != DEFAULT_ALLOW_UNREACHABLE
    ):
        options = {
            **entry.options,
            CONF_ALLOW_UNREACHABLE: entry.data[CONF_ALLOW_UNREACHABLE],
        }
        data = entry.data.copy()
        data.pop(CONF_ALLOW_UNREACHABLE)
        hass.config_entries.async_update_entry(entry, data=data, options=options)

    # Migrate allow_hue_groups from config entry data to config entry options
    if (
        CONF_ALLOW_HUE_GROUPS not in entry.options
        and CONF_ALLOW_HUE_GROUPS in entry.data
        and entry.data[CONF_ALLOW_HUE_GROUPS] != DEFAULT_ALLOW_HUE_GROUPS
    ):
        options = {
            **entry.options,
            CONF_ALLOW_HUE_GROUPS: entry.data[CONF_ALLOW_HUE_GROUPS],
        }
        data = entry.data.copy()
        data.pop(CONF_ALLOW_HUE_GROUPS)
        hass.config_entries.async_update_entry(entry, data=data, options=options)

    bridge = HueBridge(hass, entry)

    if not await bridge.async_setup():
        return False

    hass.data[DOMAIN][entry.entry_id] = bridge
    config = bridge.api.config

    # For backwards compat
    unique_id = normalize_bridge_id(config.bridgeid)
    if entry.unique_id is None:
        hass.config_entries.async_update_entry(entry, unique_id=unique_id)

    # For recovering from bug where we incorrectly assumed homekit ID = bridge ID
    elif entry.unique_id != unique_id:
        # Find entries with this unique ID
        other_entry = next(
            (
                entry
                for entry in hass.config_entries.async_entries(DOMAIN)
                if entry.unique_id == unique_id
            ),
            None,
        )

        if other_entry is None:
            # If no other entry, update unique ID of this entry ID.
            hass.config_entries.async_update_entry(entry, unique_id=unique_id)

        elif other_entry.source == config_entries.SOURCE_IGNORE:
            # There is another entry but it is ignored, delete that one and update this one
            hass.async_create_task(
                hass.config_entries.async_remove(other_entry.entry_id)
            )
            hass.config_entries.async_update_entry(entry, unique_id=unique_id)
        else:
            # There is another entry that already has the right unique ID. Delete this entry
            hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
            return False

    device_registry = await dr.async_get_registry(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, config.mac)},
        identifiers={(DOMAIN, config.bridgeid)},
        manufacturer="Signify",
        name=config.name,
        model=config.modelid,
        sw_version=config.swversion,
    )

    if config.modelid == "BSB002" and config.swversion < "1935144040":
        persistent_notification.async_create(
            hass,
            "Your Hue hub has a known security vulnerability ([CVE-2020-6007](https://cve.circl.lu/cve/CVE-2020-6007)). Go to the Hue app and check for software updates.",
            "Signify Hue",
            "hue_hub_firmware",
        )

    elif config.swupdate2_bridge_state == "readytoinstall":
        err = (
            "Please check for software updates of the bridge in the Philips Hue App.",
            "Signify Hue",
            "hue_hub_firmware",
        )
        _LOGGER.warning(err)

    return True


async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    bridge = hass.data[DOMAIN].pop(entry.entry_id)
    return await bridge.async_reset()
