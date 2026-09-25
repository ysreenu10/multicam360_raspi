

#!/usr/bin/env python3

import dbus
import dbus.service
import dbus.mainloop.glib

from gi.repository import GLib

import subprocess
import json
import threading
import time


# ============================================================
# BLE UUIDs
# ============================================================

SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"

WIFI_CHARACTERISTIC_UUID = (
    "12345678-1234-5678-1234-56789abcdef1"
)

STATUS_CHARACTERISTIC_UUID = (
    "12345678-1234-5678-1234-56789abcdef2"
)

SCAN_CHARACTERISTIC_UUID = (
    "12345678-1234-5678-1234-56789abcdef3"
)


ADVERTISEMENT_PATH = "/com/multicam/advertisement0"
SERVICE_PATH = "/com/multicam/service0"


# ============================================================
# BlueZ constants
# ============================================================

BLUEZ_SERVICE_NAME = "org.bluez"

GATT_MANAGER_IFACE = "org.bluez.GattManager1"

LE_ADVERTISING_MANAGER_IFACE = (
    "org.bluez.LEAdvertisingManager1"
)

GATT_SERVICE_IFACE = "org.bluez.GattService1"

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"

DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"


# ============================================================
# Global characteristic references
# ============================================================

STATUS_CHARACTERISTIC = None
SCAN_CHARACTERISTIC = None


# ============================================================
# D-Bus Application
# ============================================================

class Application(dbus.service.Object):

    PATH_BASE = "/com/multicam"

    def __init__(self, bus):

        self.path = self.PATH_BASE

        self.services = []

        dbus.service.Object.__init__(
            self,
            bus,
            self.path
        )

    def get_path(self):

        return dbus.ObjectPath(
            self.path
        )

    @dbus.service.method(
        "org.freedesktop.DBus.ObjectManager",
        out_signature="a{oa{sa{sv}}}"
    )
    def GetManagedObjects(self):

        response = {}

        for service in self.services:

            response[
                service.get_path()
            ] = service.get_properties()

            for characteristic in service.characteristics:

                response[
                    characteristic.get_path()
                ] = characteristic.get_properties()

        return response


# ============================================================
# BLE Service
# ============================================================

class Service(dbus.service.Object):

    def __init__(
        self,
        bus,
        index,
        uuid,
        primary
    ):

        self.path = (
            "/com/multicam/service"
            + str(index)
        )

        self.uuid = uuid

        self.primary = primary

        self.characteristics = []

        dbus.service.Object.__init__(
            self,
            bus,
            self.path
        )

    def get_path(self):

        return dbus.ObjectPath(
            self.path
        )

    def get_properties(self):

        return {

            GATT_SERVICE_IFACE: {

                "UUID":
                    self.uuid,

                "Primary":
                    self.primary,

                "Characteristics":
                    dbus.Array(
                        [
                            characteristic.get_path()
                            for characteristic
                            in self.characteristics
                        ],
                        signature="o"
                    )
            }
        }


# ============================================================
# Base BLE Characteristic
# ============================================================

class Characteristic(
    dbus.service.Object
):

    def __init__(
        self,
        bus,
        index,
        uuid,
        service,
        flags
    ):

        self.path = (
            service.path
            + "/char"
            + str(index)
        )

        self.uuid = uuid

        self.service = service

        self.flags = flags

        dbus.service.Object.__init__(
            self,
            bus,
            self.path
        )

    def get_path(self):

        return dbus.ObjectPath(
            self.path
        )

    def get_properties(self):

        return {

            GATT_CHRC_IFACE: {

                "Service":
                    self.service.get_path(),

                "UUID":
                    self.uuid,

                "Flags":
                    dbus.Array(
                        self.flags,
                        signature="s"
                    )
            }
        }


# ============================================================
# Wi-Fi Credential Characteristic
# ============================================================

class WiFiCharacteristic(
    Characteristic
):

    def __init__(
        self,
        bus,
        index,
        service
    ):

        Characteristic.__init__(
            self,
            bus,
            index,
            WIFI_CHARACTERISTIC_UUID,
            service,
            ["write"]
        )

    @dbus.service.method(
        GATT_CHRC_IFACE,
        in_signature="aya{sv}"
    )
    def WriteValue(
        self,
        value,
        options
    ):

        try:

            data = bytes(value).decode(
                "utf-8"
            )

            print()
            print(
                "========================================"
            )
            print(
                "[BLE] Wi-Fi data received"
            )
            print(
                "========================================"
            )

            print(
                "[BLE] Data:",
                data
            )

            credentials = json.loads(
                data
            )

            ssid = credentials.get(
                "ssid"
            )

            password = credentials.get(
                "password"
            )

            if not ssid:

                print(
                    "[BLE] ERROR: SSID missing."
                )

                send_status(
                    "wifi_status",
                    "failed",
                    "SSID missing"
                )

                return

            if password is None:

                print(
                    "[BLE] ERROR: Password missing."
                )

                send_status(
                    "wifi_status",
                    "failed",
                    "Password missing"
                )

                return

            print(
                f"[BLE] SSID: {ssid}"
            )

            print(
                "[BLE] Password received."
            )

            # ------------------------------------------------
            # ACK
            # ------------------------------------------------

            send_status(
                "wifi_credentials",
                "received",
                "Wi-Fi credentials received"
            )

            # ------------------------------------------------
            # Connect in background
            # ------------------------------------------------

            thread = threading.Thread(
                target=connect_wifi,
                args=(ssid, password),
                daemon=True
            )

            thread.start()

        except Exception as error:

            print(
                f"[BLE] ERROR: {error}"
            )

            send_status(
                "wifi_status",
                "failed",
                str(error)
            )


# ============================================================
# Wi-Fi Scan Characteristic
# ============================================================

class ScanCharacteristic(
    Characteristic
):

    def __init__(
        self,
        bus,
        index,
        service
    ):

        Characteristic.__init__(
            self,
            bus,
            index,
            SCAN_CHARACTERISTIC_UUID,
            service,
            ["write", "notify"]
        )

        global SCAN_CHARACTERISTIC

        SCAN_CHARACTERISTIC = self

        self.notifying = False
        self.value = []

    @dbus.service.method(
        GATT_CHRC_IFACE,
        in_signature="aya{sv}"
    )
    def WriteValue(
        self,
        value,
        options
    ):

        try:

            command = bytes(value).decode(
                "utf-8"
            ).strip()

            print(
                f"[BLE] Scan command: {command}"
            )

            if command == "SCAN_WIFI":

                thread = threading.Thread(
                    target=scan_wifi,
                    daemon=True
                )

                thread.start()

        except Exception as error:

            print(
                f"[BLE] Scan error: {error}"
            )

    @dbus.service.method(
        GATT_CHRC_IFACE,
        in_signature="",
        out_signature=""
    )
    def StartNotify(self):

        self.notifying = True

        print(
            "[BLE] Scan notifications enabled."
        )

    @dbus.service.method(
        GATT_CHRC_IFACE,
        in_signature="",
        out_signature=""
    )
    def StopNotify(self):

        self.notifying = False

        print(
            "[BLE] Scan notifications disabled."
        )

    def send(self, message):

        print(
            f"[BLE SCAN] {message}"
        )

        if not self.notifying:

            print(
                "[BLE SCAN] Notifications not enabled."
            )

            return

        self.value = [
            dbus.Byte(byte)
            for byte in message.encode("utf-8")
        ]

        self.PropertiesChanged(
            GATT_CHRC_IFACE,
            {
                "Value": dbus.Array(
                    self.value,
                    signature="y"
                )
            },
            []
        )

    @dbus.service.signal(
        DBUS_PROPERTIES_IFACE,
        signature="sa{sv}as"
    )
    def PropertiesChanged(
        self,
        interface,
        changed,
        invalidated
    ):
        pass

# ============================================================
# Status Characteristic
# ============================================================

class StatusCharacteristic(
    Characteristic
):

    def __init__(
        self,
        bus,
        index,
        service
    ):

        Characteristic.__init__(
            self,
            bus,
            index,
            STATUS_CHARACTERISTIC_UUID,
            service,
            ["notify"]
        )

        global STATUS_CHARACTERISTIC

        STATUS_CHARACTERISTIC = self

        self.notifying = False

    def send(self, message):

        if not self.notifying:

            return

        try:

            value = [
                dbus.Byte(byte)
                for byte in message.encode(
                    "utf-8"
                )
            ]

            self.PropertiesChanged(
                GATT_CHRC_IFACE,
                {
                    "Value": dbus.Array(
                        value,
                        signature="y"
                    )
                },
                []
            )

        except Exception as error:

            print(
                f"[BLE] Notification error: {error}"
            )

    @dbus.service.method(
        GATT_CHRC_IFACE,
        in_signature="",
        out_signature=""
    )
    def StartNotify(self):

        self.notifying = True

        print(
            "[BLE] Status notifications enabled."
        )

        self.send(
            json.dumps({
                "type": "ble_status",
                "status": "connected",
                "message": "BLE connected"
            })
        )

    @dbus.service.method(
        GATT_CHRC_IFACE,
        in_signature="",
        out_signature=""
    )
    def StopNotify(self):

        self.notifying = False

        print(
            "[BLE] Status notifications disabled."
        )

    @dbus.service.signal(
        DBUS_PROPERTIES_IFACE,
        signature="sa{sv}as"
    )
    def PropertiesChanged(
        self,
        interface,
        changed,
        invalidated
    ):

        pass


# ============================================================
# Send status to dashboard
# ============================================================

def send_status(
    message_type,
    status,
    message
):

    data = {

        "type":
            message_type,

        "status":
            status,

        "message":
            message
    }

    payload = json.dumps(
        data
    )

    print(
        "[BLE STATUS]",
        payload
    )

    if STATUS_CHARACTERISTIC:

        STATUS_CHARACTERISTIC.send(
            payload
        )


# ============================================================
# Send Wi-Fi scan result
# ============================================================

def send_scan_result(
    ssid,
    signal,
    security
):

    data = {

        "type":
            "wifi_scan_result",

        "ssid":
            ssid,

        "signal":
            signal,

        "security":
            security
    }

    payload = json.dumps(
        data
    )

    print(
        "[BLE SCAN]",
        payload
    )

    if SCAN_CHARACTERISTIC:

        SCAN_CHARACTERISTIC.send(
            payload
        )


# ============================================================
# Wi-Fi Scan
# ============================================================

def scan_wifi():

    print()
    print(
        "[WIFI] Scanning networks..."
    )

    send_status(
        "wifi_scan",
        "started",
        "Scanning Wi-Fi networks..."
    )

    try:

        result = subprocess.run(
            [
                "nmcli",
                "-t",
                "-f",
                "SSID,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
                "--rescan",
                "yes"
            ],
            capture_output=True,
            text=True,
            timeout=20
        )

        if result.returncode != 0:

            print(
                "[WIFI] Scan failed:",
                result.stderr.strip()
            )

            send_status(
                "wifi_scan",
                "failed",
                "Wi-Fi scan failed"
            )

            return

        networks = {}

        for line in result.stdout.splitlines():

            parts = line.split(":")

            if len(parts) < 3:

                continue

            ssid = parts[0].strip()
            signal = parts[1].strip()
            security = ":".join(
                parts[2:]
            ).strip()

            if not ssid:

                continue

            networks[ssid] = (
                signal,
                security
            )

        for ssid, values in networks.items():

            signal, security = values

            send_scan_result(
                ssid,
                signal,
                security
            )

            time.sleep(0.05)

        send_status(
            "wifi_scan",
            "complete",
            f"{len(networks)} Wi-Fi networks found"
        )

        print(
            f"[WIFI] Found {len(networks)} networks."
        )

    except Exception as error:

        print(
            f"[WIFI] Scan error: {error}"
        )

        send_status(
            "wifi_scan",
            "failed",
            str(error)
        )


# ============================================================
# Wi-Fi Connection
# ============================================================

def connect_wifi(
    ssid,
    password
):

    print()
    print(
        "[WIFI] Connecting..."
    )

    send_status(
        "wifi_status",
        "connecting",
        f"Connecting to {ssid}..."
    )

    try:

        result = subprocess.run(
            [
                "nmcli",
                "device",
                "wifi",
                "connect",
                ssid,
                "password",
                password
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:

            print()
            print(
                "[WIFI] ==============================="
            )

            print(
                "[WIFI] CONNECTED SUCCESSFULLY"
            )

            print(
                "[WIFI] ==============================="
            )

            print(
                result.stdout.strip()
            )

            send_status(
                "wifi_status",
                "connected",
                f"Connected to {ssid}"
            )

        else:

            print()
            print(
                "[WIFI] CONNECTION FAILED"
            )

            print(
                result.stderr.strip()
            )

            send_status(
                "wifi_status",
                "failed",
                f"Failed to connect to {ssid}"
            )

    except subprocess.TimeoutExpired:

        print(
            "[WIFI] Connection timeout."
        )

        send_status(
            "wifi_status",
            "failed",
            "Wi-Fi connection timeout"
        )

    except Exception as error:

        print(
            f"[WIFI] ERROR: {error}"
        )

        send_status(
            "wifi_status",
            "failed",
            str(error)
        )


# ============================================================
# BLE Advertisement
# ============================================================

class Advertisement(
    dbus.service.Object
):

    def __init__(
        self,
        bus,
        index
    ):

        self.path = (
            "/com/multicam/advertisement"
            + str(index)
        )

        self.bus = bus

        dbus.service.Object.__init__(
            self,
            bus,
            self.path
        )

    def get_path(self):

        return dbus.ObjectPath(
            self.path
        )

    @dbus.service.method(
        DBUS_PROPERTIES_IFACE,
        in_signature="s",
        out_signature="a{sv}"
    )
    def GetAll(
        self,
        interface
    ):

        if interface != LE_ADVERTISEMENT_IFACE:

            return {}

        return {

            "Type":
                "peripheral",

            "ServiceUUIDs":
                dbus.Array(
                    [SERVICE_UUID],
                    signature="s"
                ),

            "LocalName":
                "MULTICAM-SETUP"
        }

    @dbus.service.method(
        LE_ADVERTISEMENT_IFACE,
        in_signature="",
        out_signature=""
    )
    def Release(self):

        print(
            "[BLE] Advertisement released."
        )


# ============================================================
# Main
# ============================================================

def main():

    dbus.mainloop.glib.DBusGMainLoop(
        set_as_default=True
    )

    bus = dbus.SystemBus()

    print()
    print(
        "========================================"
    )

    print(
        "       MULTICAM BLE WIFI SERVER"
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # Get Bluetooth adapter
    # --------------------------------------------------------

    adapter_path = None

    object_manager = dbus.Interface(
        bus.get_object(
            BLUEZ_SERVICE_NAME,
            "/"
        ),
        "org.freedesktop.DBus.ObjectManager"
    )

    objects = (
        object_manager.GetManagedObjects()
    )

    for path, interfaces in objects.items():

        if (
            "org.bluez.GattManager1"
            in interfaces
        ):

            adapter_path = path

            break

    if adapter_path is None:

        print(
            "[ERROR] Bluetooth adapter not found."
        )

        return

    print(
        f"[BLE] Adapter: {adapter_path}"
    )

    # --------------------------------------------------------
    # Create application
    # --------------------------------------------------------

    app = Application(
        bus
    )

    service = Service(
        bus,
        0,
        SERVICE_UUID,
        True
    )

    wifi_characteristic = (
        WiFiCharacteristic(
            bus,
            0,
            service
        )
    )

    status_characteristic = (
        StatusCharacteristic(
            bus,
            1,
            service
        )
    )

    scan_characteristic = (
        ScanCharacteristic(
            bus,
            2,
            service
        )
    )

    service.characteristics.append(
        wifi_characteristic
    )

    service.characteristics.append(
        status_characteristic
    )

    service.characteristics.append(
        scan_characteristic
    )

    app.services.append(
        service
    )

    # --------------------------------------------------------
    # Advertisement
    # --------------------------------------------------------

    advertisement = Advertisement(
        bus,
        0
    )

    # --------------------------------------------------------
    # Register GATT
    # --------------------------------------------------------

    gatt_manager = dbus.Interface(
        bus.get_object(
            BLUEZ_SERVICE_NAME,
            adapter_path
        ),
        GATT_MANAGER_IFACE
    )

    gatt_manager.RegisterApplication(
        app.get_path(),
        {},
        reply_handler=lambda:
            print(
                "[BLE] GATT application registered."
            ),
        error_handler=lambda error:
            print(
                "[BLE] GATT registration error:",
                error
            )
    )

    # --------------------------------------------------------
    # Register advertisement
    # --------------------------------------------------------

    advertising_manager = dbus.Interface(
        bus.get_object(
            BLUEZ_SERVICE_NAME,
            adapter_path
        ),
        LE_ADVERTISING_MANAGER_IFACE
    )

    advertising_manager.RegisterAdvertisement(
        advertisement.get_path(),
        {},
        reply_handler=lambda:
            print(
                "[BLE] Advertisement started."
            ),
        error_handler=lambda error:
            print(
                "[BLE] Advertisement error:",
                error
            )
    )

    print()
    print(
        "[BLE] Device name : MULTICAM-SETUP"
    )

    print(
        "[BLE] Waiting for dashboard..."
    )

    print()

    # --------------------------------------------------------
    # GLib event loop
    # --------------------------------------------------------

    mainloop = GLib.MainLoop()

    try:

        mainloop.run()

    except KeyboardInterrupt:

        print()
        print(
            "[BLE] Server stopped."
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()