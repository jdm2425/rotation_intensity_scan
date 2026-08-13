"""
base.py

Abstract base class for all motorised rotation stages.

Every rotation stage used by the project must implement this
interface so that experiment code can remain completely independent
of the underlying hardware driver.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .base import HardwareDevice


class BaseRotationStage(HardwareDevice, ABC):
    """
    Common interface for any motorised rotation stage.
    """

    def __init__(
        self,
        serial: str,
        name: str = "Rotation Stage",
    ):

        super().__init__(name=name)

        self.serial = str(serial)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """
        Connect to the hardware.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """
        Disconnect from the hardware.
        """

    # ------------------------------------------------------------------
    # Motion
    # ------------------------------------------------------------------

    @abstractmethod
    def home(self) -> None:
        """
        Home the stage.
        """

    @abstractmethod
    def move_to(
        self,
        angle_deg: float,
    ) -> None:
        """
        Move to an absolute angle.
        """

    @abstractmethod
    def move_by(
        self,
        angle_deg: float,
    ) -> None:
        """
        Move by a relative angle.
        """

    @abstractmethod
    def stop(self) -> None:
        """
        Immediately stop motion.
        """

    @abstractmethod
    def wait(self) -> None:
        """
        Block until motion has finished.
        """

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def position(self) -> float:
        """
        Current angular position in degrees.
        """

    @property
    @abstractmethod
    def is_moving(self) -> bool:
        """
        True while the stage is moving.
        """

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def info(self) -> dict:
        """
        Return a summary of the device.
        """

        return {
            "name": self.name,
            "serial": self.serial,
            "connected": self.connected,
            "position_deg": (
                self.position
                if self.connected
                else None
            ),
        }

    def __repr__(self):

        if self.connected:

            return (
                f"<{self.__class__.__name__} "
                f"serial='{self.serial}' "
                f"position={self.position:.4f}Â°>"
            )

        return (
            f"<{self.__class__.__name__} "
            f"serial='{self.serial}' "
            f"(disconnected)>"
        )
