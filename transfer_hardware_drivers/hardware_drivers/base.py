"""
base.py

Abstract base class for all laboratory hardware devices.

Every hardware device in the project should inherit from HardwareDevice.

Provides
--------
- connection state
- context manager support
- common logging
- connection checking
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class HardwareError(RuntimeError):
    """Base class for hardware-related errors."""


class DeviceNotConnectedError(HardwareError):
    """Raised when a device command is issued before connecting."""


# =============================================================================
# Base class
# =============================================================================


class HardwareDevice(ABC):
    """
    Abstract base class for every hardware device.
    """

    def __init__(self, name: str):

        self.name = name
        self._connected = False

    # ------------------------------------------------------------------
    # Required API
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """Connect to the hardware."""

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the hardware."""

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """True if the device is connected."""
        return self._connected

    def _set_connected(self, state: bool) -> None:
        """Used by subclasses after a successful connect/disconnect."""
        self._connected = bool(state)

    def require_connection(self) -> None:
        """Raise if the device is not connected."""

        if not self.connected:
            raise DeviceNotConnectedError(
                f"{self.name} is not connected."
            )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):

        self.connect()

        return self

    def __exit__(self, exc_type, exc, tb):

        self.disconnect()

        return False

    # ------------------------------------------------------------------
    # Information
    # ------------------------------------------------------------------

    def info(self) -> dict:

        return {
            "name": self.name,
            "connected": self.connected,
        }

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self):

        state = "connected" if self.connected else "disconnected"

        return (
            f"<{self.__class__.__name__} "
            f"name='{self.name}' "
            f"state='{state}'>"
        )
