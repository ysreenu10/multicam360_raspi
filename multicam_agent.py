#!/usr/bin/env python3

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
import urllib.error


# ============================================================
# CONFIGURATION
# ============================================================

DEVICE_ID = "MCAM-001"

# CHANGE THIS to your laptop's IP address
# SERVER_IP = "100.78.67.59" //sreenu ip 
SERVER_IP = "100.127.44.4" #lokesh ip 

SERVER_PORT = 8000

HEARTBEAT_INTERVAL = 10

HEARTBEAT_URL = (
    f"http://{SERVER_IP}:{SERVER_PORT}"
    "/api/device/heartbeat"
)


# Existing MultiCam services
CAMERA_SERVICE = "multicam-controller.service"
UPLOADER_SERVICE = "multicam-uploader.service"
BLE_SERVICE = "multicam-ble.service"


# ============================================================
# COMMAND HELPER
# ============================================================

def run_command(command, timeout=5):

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return result.stdout.strip()

    except Exception:
        return ""


# ============================================================
# PI IP ADDRESS
# ============================================================

def get_ip_address():

    output = run_command(
        ["hostname", "-I"]
    )

    if not output:
        return "unknown"

    addresses = output.split()

    # Prefer normal IPv4 address
    for address in addresses:

        if "." in address:

            return address

    return addresses[0] if addresses else "unknown"


# ============================================================
# WIFI STATUS
# ============================================================

def get_wifi_status():

    output = run_command([
        "nmcli",
        "-t",
        "-f",
        "DEVICE,TYPE,STATE,CONNECTION",
        "device"
    ])

    for line in output.splitlines():

        parts = line.split(":")

        if len(parts) < 4:
            continue

        device = parts[0]
        device_type = parts[1]
        state = parts[2]
        connection = parts[3]

        if device_type == "wifi":

            if state == "connected":

                return {
                    "status": "connected",
                    "ssid": connection
                }

            elif state:

                return {
                    "status": state,
                    "ssid": ""
                }

    return {
        "status": "disconnected",
        "ssid": ""
    }


# ============================================================
# BLE STATUS
# ============================================================

def get_ble_status():

    output = run_command([
        "bluetoothctl",
        "show"
    ])

    if not output:

        return "unknown"

    for line in output.splitlines():

        line = line.strip()

        if line.startswith("Powered:"):

            powered = line.split(":", 1)[1].strip()

            if powered.lower() == "yes":

                return "powered"

            return "off"

    return "unknown"


# ============================================================
# SYSTEMD SERVICE STATUS
# ============================================================

def get_service_status(service_name):

    output = run_command([
        "systemctl",
        "is-active",
        service_name
    ])

    if output == "active":

        return "running"

    if output == "inactive":

        return "stopped"

    if output == "failed":

        return "failed"

    if output == "activating":

        return "starting"

    return output if output else "unknown"


# ============================================================
# CPU USAGE
# ============================================================

def read_cpu_times():

    try:

        with open("/proc/stat", "r") as file:

            line = file.readline()

        parts = line.split()

        if parts[0] != "cpu":

            return None

        values = list(
            map(int, parts[1:])
        )

        idle = values[3]

        total = sum(values)

        return total, idle

    except Exception:

        return None


def get_cpu_percent():

    first = read_cpu_times()

    if not first:

        return 0.0

    time.sleep(0.2)

    second = read_cpu_times()

    if not second:

        return 0.0

    total1, idle1 = first
    total2, idle2 = second

    total_delta = total2 - total1
    idle_delta = idle2 - idle1

    if total_delta <= 0:

        return 0.0

    usage = (
        (total_delta - idle_delta)
        / total_delta
    ) * 100

    return round(usage, 1)


# ============================================================
# MEMORY USAGE
# ============================================================

def get_memory_percent():

    try:

        mem_total = 0
        mem_available = 0

        with open("/proc/meminfo", "r") as file:

            for line in file:

                if line.startswith("MemTotal:"):

                    mem_total = int(
                        line.split()[1]
                    )

                elif line.startswith("MemAvailable:"):

                    mem_available = int(
                        line.split()[1]
                    )

        if mem_total == 0:

            return 0.0

        used = mem_total - mem_available

        percentage = (
            used / mem_total
        ) * 100

        return round(percentage, 1)

    except Exception:

        return 0.0


# ============================================================
# DISK USAGE
# ============================================================

def get_disk_percent():

    try:

        total, used, free = shutil.disk_usage("/")

        percentage = (
            used / total
        ) * 100

        return round(percentage, 1)

    except Exception:

        return 0.0


# ============================================================
# BUILD HEARTBEAT
# ============================================================

def create_heartbeat():

    wifi = get_wifi_status()

    data = {

        "device_id": DEVICE_ID,

        "ip_address": get_ip_address(),

        "wifi_status": wifi["status"],

        "wifi_ssid": wifi["ssid"],

        "ble_status": get_ble_status(),

        "ble_service": get_service_status(
        BLE_SERVICE
        ),

        "camera_service": get_service_status(
            CAMERA_SERVICE
        ),

        "uploader_service": get_service_status(
            UPLOADER_SERVICE
        ),

        "cpu_percent": get_cpu_percent(),

        "memory_percent": get_memory_percent(),

        "disk_percent": get_disk_percent()
    }

    return data


# ============================================================
# SEND HEARTBEAT
# ============================================================

def send_heartbeat(data):

    json_data = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        HEARTBEAT_URL,
        data=json_data,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=5
        ) as response:

            response_data = response.read().decode(
                "utf-8"
            )

            return True, response_data

    except urllib.error.HTTPError as error:

        return False, (
            f"HTTP {error.code}: "
            f"{error.reason}"
        )

    except urllib.error.URLError as error:

        return False, (
            f"Connection error: "
            f"{error.reason}"
        )

    except Exception as error:

        return False, str(error)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("          MULTICAM MONITORING AGENT")
    print("=" * 60)

    print(f"[AGENT] Device ID : {DEVICE_ID}")
    print(f"[AGENT] Server    : {SERVER_IP}:{SERVER_PORT}")
    print(f"[AGENT] Heartbeat: {HEARTBEAT_INTERVAL} seconds")
    print()

    while True:

        try:

            data = create_heartbeat()

            print("-" * 60)

            print(
                f"[DEVICE] {data['device_id']}"
            )

            print(
                f"[IP] {data['ip_address']}"
            )

            print(
                f"[WIFI] "
                f"{data['wifi_status']} "
                f"{data['wifi_ssid']}"
            )

            print(
                f"[BLE] "
                f"{data['ble_status']}"
            )
            print(
                f"[BLE SERVICE] "
                f"{data['ble_service']}"
            ) 

            print(
                f"[CAMERA] "
                f"{data['camera_service']}"
            )

            print(
                f"[UPLOADER] "
                f"{data['uploader_service']}"
            )

            print(
                f"[CPU] "
                f"{data['cpu_percent']}%"
            )

            print(
                f"[MEMORY] "
                f"{data['memory_percent']}%"
            )

            print(
                f"[DISK] "
                f"{data['disk_percent']}%"
            )

            success, response = send_heartbeat(
                data
            )

            if success:

                print(
                    "[SERVER] Heartbeat sent successfully"
                )

                print(
                    f"[SERVER] {response}"
                )

            else:

                print(
                    "[SERVER] Heartbeat failed"
                )

                print(
                    f"[SERVER] {response}"
                )

        except KeyboardInterrupt:

            print()
            print("[AGENT] Stopped by user.")
            break

        except Exception as error:

            print(
                f"[AGENT] Error: {error}"
            )

        time.sleep(
            HEARTBEAT_INTERVAL
        )


if __name__ == "__main__":

    main()