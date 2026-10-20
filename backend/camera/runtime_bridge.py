"""Explicit approved camera-mode control of the existing temporary binary bridge.

No flashing, ROM-mode assertion, target reset or arbitrary serial commands.
The primary telemetry firmware cannot perform this role and is never replaced here.
"""
import logging
import secrets
import time
from scripts import uart_programmer_bridge as transport


class RuntimeBridge:
    def __init__(self, port, clock=time.monotonic, approval=None):
        self.port, self.clock = port, clock
        self.approval = approval
        self.nonce = secrets.randbits(32)
        self.attempted = False
        self.last_ping = None

    def start(self):
        from backend.camera.hardware_gate import validate_approval
        try:
            validate_approval(self.approval)
            if self.approval.get("relay_control") != "programmer_runtime_v1":
                raise ValueError("Runtime bridge role must be explicitly approved")
        except ValueError as exc:
            raise transport.BridgeError(str(exc)) from exc
        transport.inspect_bridge(self.port)
        # Unlike the programming controller, this role requires verified NORMAL
        # camera boot. It must not claim target_download_mode=True.
        self.attempted = True
        transport.write_all(self.port.write, transport.ARM)
        transport.validate_status(transport.read_status(self.port), "raw")
        self.keepalive(force=True)

    def keepalive(self, force=False):
        now = self.clock()
        if force or self.last_ping is None or now-self.last_ping >= 5:
            transport.write_all(self.port.write, ("PING "+str(self.nonce)+"\n").encode("ascii"))
            self.last_ping = now

    def stop(self):
        if self.attempted:
            logging.getLogger(__name__).info("Stopping relay TX; waiting about32s for verified UART2 shutdown")
            transport.wait_locked(self.port)
            self.attempted = False
