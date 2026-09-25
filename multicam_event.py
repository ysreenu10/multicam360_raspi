#!/usr/bin/env python3

import json
import urllib.request
import urllib.error


# ============================================================
# CONFIGURATION
# ============================================================

DEVICE_ID = "MCAM-001"

SERVER_IP = "100.78.67.59"
SERVER_PORT = 8000

EVENT_URL = (
    f"http://{SERVER_IP}:{SERVER_PORT}"
    "/api/event"
)


# ============================================================
# SEND EVENT
# ============================================================

def send_event(
    source,
    event_type,
    message,
    camera_id=None,
    filename=None
):

    data = {
        "device_id": DEVICE_ID,
        "source": source,
        "event_type": event_type,
        "message": message,
        "camera_id": camera_id,
        "filename": filename
    }

    payload = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        EVENT_URL,
        data=payload,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=3
        ) as response:

            return True

    except Exception:

        # IMPORTANT:
        # Dashboard failure must NEVER stop
        # camera/uploader/BLE operation.

        return False


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    success = send_event(
        source="system",
        event_type="test_event",
        message="MultiCam event system test"
    )

    if success:

        print("[EVENT] Sent successfully")

    else:

        print("[EVENT] Failed to send")