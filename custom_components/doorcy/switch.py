"""A switch per Doorcy scene."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DoorcyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one switch per scene."""
    coordinator: DoorcyCoordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [guid for guid in coordinator.data if guid not in known]
        known.update(new)
        async_add_entities(DoorcyScene(coordinator, guid) for guid in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


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
        return bool(self._scene.get("active"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"scene_id": self._scene.get("id"), "device_id": self._device_id}

    async def _async_set(self, on: bool) -> None:
        await self.coordinator.client.async_set_scene(self._device_id, self._guid, on)
        # Reflect it immediately; the live message confirms (or corrects) it.
        self.coordinator.async_set_updated_data(
            {
                **self.coordinator.data,
                self._guid: {**self._scene, "active": on},
            }
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)
