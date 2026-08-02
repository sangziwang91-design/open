"""Authenticated browser-to-executor bridge."""

from .protocol import BrainTaskMessage, BridgeResultMessage

__all__ = ["BrainTaskMessage", "BridgeResultMessage"]
