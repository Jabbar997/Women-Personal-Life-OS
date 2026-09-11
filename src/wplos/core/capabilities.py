from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DeviceCapability(StrEnum):
    """Something the client may or may not be allowed to do.

    The operating system owns these answers, so the core must treat every one of
    them as absent until told otherwise.
    """

    NOTIFICATIONS = "NOTIFICATIONS"
    CALENDAR = "CALENDAR"
    CAMERA = "CAMERA"
    PHOTOS = "PHOTOS"
    MICROPHONE = "MICROPHONE"
    LOCATION_COARSE = "LOCATION_COARSE"
    LOCATION_PRECISE = "LOCATION_PRECISE"
    CONTACTS = "CONTACTS"
    HEALTH = "HEALTH"
    BACKGROUND_REFRESH = "BACKGROUND_REFRESH"


class CapabilityState(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    RESTRICTED = "RESTRICTED"
    REVOKED = "REVOKED"

    @property
    def is_usable(self) -> bool:
        return self is CapabilityState.GRANTED


class CapabilitySet(BaseModel):
    """What this client can currently do. Absence is the default answer.

    A refused permission degrades a feature; it never breaks the core, so every
    lookup for an undeclared capability returns ``NOT_REQUESTED`` rather than
    raising.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    states: dict[DeviceCapability, CapabilityState] = Field(default_factory=dict)

    @classmethod
    def none_granted(cls) -> "CapabilitySet":
        return cls()

    def state_of(self, capability: DeviceCapability) -> CapabilityState:
        return self.states.get(capability, CapabilityState.NOT_REQUESTED)

    def allows(self, capability: DeviceCapability) -> bool:
        return self.state_of(capability).is_usable

    def granted(self) -> frozenset[DeviceCapability]:
        return frozenset(capability for capability in DeviceCapability if self.allows(capability))

    def with_state(self, capability: DeviceCapability, state: CapabilityState) -> "CapabilitySet":
        return CapabilitySet(states={**self.states, capability: state})
