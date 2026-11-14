"""An event entity per Doorcy scene: fires when the scene is started."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SceneStatus
from .const import DOMAIN, EVENT_SCENE_STARTED
from .coordinator import DoorcyCoordinator, scene_started_signal


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one event entity per scene."""
    coordinator: DoorcyCoordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [guid for guid in coordinator.data if guid not in known]
        known.update(new)
        async_add_entities(DoorcySceneStarted(coordinator, guid) for guid in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class DoorcySceneStarted(EventEntity):
    """Fires `scene_started` every time the scene is started.

    Unlike the switch, which shows the state, this never misses a short pulse
    that is over again a moment later.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_event_types = [EVENT_SCENE_STARTED]
    _attr_translation_key = "scene_started"

    def __init__(self, coordinator: DoorcyCoordinator, guid: str) -> None:
        scene = coordinator.data[guid]
        self._coordinator = coordinator
        self._guid = guid
        self._device_id: str = scene["device"]
        self._attr_translation_placeholders = {"scene": scene.get("label") or guid}
        self._attr_unique_id = f"doorcy_scene_started_{guid}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=coordinator.devices.get(self._device_id, self._device_id),
            manufacturer="Doorcy",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                scene_started_signal(self._coordinator.config_entry.entry_id),
                self._handle_started,
            )
        )

    @callback
    def _handle_started(self, guid: str, status: SceneStatus) -> None:
        if guid != self._guid:
            return
        self._trigger_event(
            EVENT_SCENE_STARTED,
            {
                "scene_id": status.scene_id,
                "device_id": status.device_id,
                "started_at": status.timestamp.isoformat(),
            },
        )
        self.async_write_ha_state()
