"""
MemoryOS Resource Monitor.
Tracks CPU and RAM consumption of the background desktop agent process.
Logs resource metrics and asserts that idle performance stays strictly under 3% CPU and 150MB RAM.
"""

import logging
import os
import time
from typing import Dict, Tuple
import psutil

from backend.config import MAX_IDLE_CPU_PERCENT, MAX_IDLE_RAM_MB
from desktop_agent.window_tracker import is_user_idle

logger = logging.getLogger("memoryos.resource_monitor")


class AgentResourceMonitor:
    """Monitors memory and CPU metrics for the agent daemon."""

    def __init__(self):
        self.process = psutil.Process(os.getpid())
        # Initial prime call for cpu_percent
        self.process.cpu_percent(interval=None)

    def sample(self) -> Dict[str, float]:
        """Sample current CPU% and RAM usage in MB."""
        cpu = self.process.cpu_percent(interval=None)
        mem_info = self.process.memory_info()
        ram_mb = round(mem_info.rss / (1024 * 1024), 2)

        return {
            "cpu_percent": round(cpu, 2),
            "ram_mb": ram_mb,
            "is_idle": is_user_idle()
        }

    def check_thresholds(self) -> Tuple[bool, str]:
        """
        Verify that agent stays within idle performance bounds:
        Under 3% CPU and under 150MB RAM when idle.
        Returns (is_compliant, message).
        """
        metrics = self.sample()
        cpu = metrics["cpu_percent"]
        ram = metrics["ram_mb"]
        idle = metrics["is_idle"]

        if idle:
            if cpu > MAX_IDLE_CPU_PERCENT:
                msg = f"RESOURCE VIOLATION: Idle CPU ({cpu}%) exceeded threshold ({MAX_IDLE_CPU_PERCENT}%)!"
                logger.error(msg)
                return False, msg

            if ram > MAX_IDLE_RAM_MB:
                msg = f"RESOURCE VIOLATION: Idle RAM ({ram} MB) exceeded threshold ({MAX_IDLE_RAM_MB} MB)!"
                logger.error(msg)
                return False, msg

        return True, f"OK (CPU: {cpu}%, RAM: {ram}MB, Idle: {idle})"

