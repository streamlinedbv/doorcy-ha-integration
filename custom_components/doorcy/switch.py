"""A switch per Doorcy scene."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DoorcyCoordinator


def _is_active(value: Any) -> bool:
    """The API sends "true"/"false" as strings, not JSON booleans."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one switch per scene."""
    coordinator: DoorcyCoordinator = entry.runtime_data
    async_add_entities(DoorcyScene(coordinator, guid) for guid in coordinator.data)


class DoorcyScene(CoordinatorEntity[DoorcyCoordinator], SwitchEntity):
    """A Doorcy scene, switchable on and off.

    A switch rather than a `scene` entity: HA scenes are activate-only,
    while Doorcy exposes both status/on and status/off.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: DoorcyCoordinator, guid: str) -> None:
        super().__init__(coordinator)
        scene = coordinator.data[guid]
        self._guid = guid
        self._device_id: str = scene["device"]
        self._attr_name = scene.get("label") or guid
        self._attr_unique_id = f"doorcy_scene_{guid}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=coordinator.devices.get(self._device_id, self._device_id),
            manufacturer="Doorcy",
        )

    @property
    def _scene(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._guid, {})

    @property
    def available(self) -> bool:
        return super().available and bool(self._scene)

    @property
    def is_on(self) -> bool:
        return _is_active(self._scene.get("active"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"scene_id": self._scene.get("id"), "device_id": self._device_id}

    async def _async_set(self, on: bool) -> None:
        await self.coordinator.client.async_set_scene(self._device_id, self._guid, on)
        # Reflect it immediately; the next poll confirms.
        self._scene["active"] = "true" if on else "false"
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)
