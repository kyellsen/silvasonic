"""Silvasonic Controller Service Package."""

from silvasonic.controller.podman_client import SilvasonicPodmanClient
from silvasonic.core import __version__

__all__ = ["SilvasonicPodmanClient", "__version__"]
