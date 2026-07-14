"""
base.py

Abstract base class for all experiments.

Every experiment in the project should inherit from BaseExperiment.

Responsibilities
----------------
- Own a HardwareManager
- Connect/disconnect hardware
- Provide test mode
- Provide save mode
- Provide logging
- Time experiment execution

Concrete experiments only need to implement run().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import time

from hardware.hardware_manager import HardwareManager

logger = logging.getLogger(__name__)


class BaseExperiment(ABC):
    """
    Base class for all experiments.
    """

    def __init__(
        self,
        hardware: HardwareManager | None = None,
        *,
        test_mode: bool = False,
        save: bool = True,
    ):
        """
        Parameters
        ----------
        hardware
            Existing HardwareManager. If omitted, one is created.

        test_mode
            If True, exercise all hardware but do not save data.

        save
            Enable data saving.
        """

        self.hardware = hardware or HardwareManager()

        self.test_mode = bool(test_mode)

        # Never save while testing
        self.save = bool(save) and not self.test_mode

        self._connected_here = False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):

        if not self.hardware.waveplate.connected:

            logger.info("Connecting hardware...")

            self.hardware.connect_all()

            self._connected_here = True

        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):

        if self._connected_here:

            logger.info("Disconnecting hardware...")

            self.hardware.disconnect_all()

        return False

    # ------------------------------------------------------------------
    # Experiment lifecycle
    # ------------------------------------------------------------------

    def execute(self):
        """
        Execute the experiment while timing it.
        """

        logger.info("=" * 60)
        logger.info("Starting experiment: %s", self.__class__.__name__)

        if self.test_mode:
            logger.info("Running in TEST MODE")

        start = time.perf_counter()

        with self:

            result = self.run()

        elapsed = time.perf_counter() - start

        logger.info(
            "Finished in %.2f s",
            elapsed,
        )

        logger.info("=" * 60)

        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def log(self, message: str):

        logger.info(message)

    # ------------------------------------------------------------------
    # Required API
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self):
        """
        Execute the experiment.

        Must be implemented by subclasses.
        """
        raise NotImplementedError