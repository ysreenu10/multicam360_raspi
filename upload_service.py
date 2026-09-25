

#!/usr/bin/env python3

import json
import subprocess
import time

from pathlib import Path

import requests

# Dashboard event reporting
from multicam_event import send_event


# ============================================================
# CONFIG
# ============================================================

CONFIG_FILE = Path(
    "/home/raspi5/multicam/multicam_config.json"
)

RASPI_MAC = (
    "88:a2:9e:cf:ee:35"
)


# ============================================================
# LOAD CONFIG
# ============================================================

def load_config():

    if not CONFIG_FILE.exists():

        raise FileNotFoundError(
            f"Config file not found: "
            f"{CONFIG_FILE}"
        )


    with open(
        CONFIG_FILE,
        "r"
    ) as file:

        return json.load(file)


CONFIG = load_config()


# ============================================================
# CONFIG VALUES
# ============================================================

MEDIA_DIR = Path(
    CONFIG["storage"]["base_dir"]
)


SERVER = CONFIG["server"]


LAPTOP_IP = SERVER["ip"]

PORT = int(
    SERVER["port"]
)


UPLOAD_URL = (

    f"http://"
    f"{LAPTOP_IP}:"
    f"{PORT}"
    f"{SERVER['upload_endpoint']}"

)


HEALTH_URL = (

    f"http://"
    f"{LAPTOP_IP}:"
    f"{PORT}"
    f"{SERVER['health_endpoint']}"

)


UPLOADER = CONFIG["uploader"]


CHECK_INTERVAL = int(

    UPLOADER.get(
        "check_interval",
        10
    )

)


FILE_STABLE_TIME = int(

    UPLOADER.get(
        "file_stable_time",
        3
    )

)


DELETE_AFTER_UPLOAD = bool(

    UPLOADER.get(
        "delete_after_upload",
        True
    )

)


# ============================================================
# STATISTICS
# ============================================================

total_uploaded_bytes = 0

total_uploaded_files = 0


# ============================================================
# FORMAT BYTES
# ============================================================

def format_bytes(num_bytes):

    if num_bytes < 1024:

        return f"{num_bytes:.2f} B"

    if num_bytes < 1024 * 1024:

        return f"{num_bytes / 1024:.2f} KiB"

    if num_bytes < 1024 * 1024 * 1024:

        return f"{num_bytes / (1024 * 1024):.2f} MiB"

    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GiB"
# ============================================================
# CAMERA ID
# ============================================================

def get_camera_id(
    file_path
):

    for camera in CONFIG["cameras"]:

        camera_id = (
            camera["camera_id"]
        )


        if camera_id in (
            file_path.parts
        ):

            return camera_id


    return None


# ============================================================
# MEDIA TYPE
# ============================================================

def get_media_type(
    file_path
):

    extension = (
        file_path.suffix.lower()
    )


    if extension == ".mp4":

        return "video"


    if extension in (
        ".jpg",
        ".jpeg"
    ):

        return "image"


    return None


# ============================================================
# SERVER HEALTH
# ============================================================

def check_server():

    try:

        start_time = (
            time.perf_counter()
        )


        response = requests.get(

            HEALTH_URL,

            timeout=5

        )


        latency_ms = (

            time.perf_counter()
            - start_time

        ) * 1000


        if response.status_code == 200:

            return True, latency_ms


        return False, latency_ms


    except requests.RequestException:

        return False, None


# ============================================================
# FILE STABILITY
# ============================================================

def is_file_stable(
    file_path
):

    try:

        size1 = (
            file_path
            .stat()
            .st_size
        )


        time.sleep(
            FILE_STABLE_TIME
        )


        size2 = (
            file_path
            .stat()
            .st_size
        )


        return (
            size1 == size2
        )


    except FileNotFoundError:

        return False


# ============================================================
# VIDEO METADATA
# ============================================================

def get_video_metadata(

    file_path,

    camera_id

):

    command = [

        "ffprobe",

        "-v",
        "error",

        "-select_streams",
        "v:0",

        "-show_entries",

        (
            "format=duration,size,bit_rate:"
            "stream=codec_name,width,height,"
            "r_frame_rate,bit_rate"
        ),

        "-of",
        "json",

        str(file_path)

    ]


    try:

        result = subprocess.run(

            command,

            capture_output=True,

            text=True,

            timeout=15

        )


        if result.returncode != 0:

            return {}


        data = json.loads(
            result.stdout
        )


        format_data = data.get(
            "format",
            {}
        )


        streams = data.get(
            "streams",
            []
        )


        stream = (

            streams[0]

            if streams

            else {}

        )


        try:

            duration = float(

                format_data.get(
                    "duration",
                    0
                )

            )

        except (
            TypeError,
            ValueError
        ):

            duration = 0.0


        try:

            file_size = int(

                format_data.get(
                    "size"
                )

            )

        except (
            TypeError,
            ValueError
        ):

            file_size = (
                file_path
                .stat()
                .st_size
            )


        width = stream.get(
            "width"
        )


        height = stream.get(
            "height"
        )


        codec = stream.get(
            "codec_name"
        )


        frame_rate = stream.get(
            "r_frame_rate"
        )


        fps = None


        if (

            frame_rate

            and

            "/" in frame_rate

        ):

            numerator, denominator = (
                frame_rate.split(
                    "/",
                    1
                )
            )


            if float(
                denominator
            ) != 0:

                fps = round(

                    float(
                        numerator
                    )
                    /
                    float(
                        denominator
                    ),

                    2

                )


        bitrate = (

            stream.get(
                "bit_rate"
            )

            or

            format_data.get(
                "bit_rate"
            )

        )


        bitrate_mbps = None


        if bitrate:

            try:

                bitrate_mbps = round(

                    int(
                        bitrate
                    )
                    /
                    1_000_000,

                    3

                )

            except (
                TypeError,
                ValueError
            ):

                pass


        total_seconds = int(
            duration
        )


        hours = (
            total_seconds
            // 3600
        )


        minutes = (

            (total_seconds % 3600)
            // 60

        )


        seconds = (
            total_seconds % 60
        )


        return {

            "camera_id":
                camera_id,

            "filename":
                file_path.name,

            "duration_seconds":
                round(
                    duration,
                    3
                ),

            "duration":
                (
                    f"{hours:02d}:"
                    f"{minutes:02d}:"
                    f"{seconds:02d}"
                ),

            "file_size_bytes":
                file_size,

            "file_size":
                format_bytes(
                    file_size
                ),

            "resolution":
                (
                    f"{width}x{height}"

                    if width and height

                    else None
                ),

            "width":
                width,

            "height":
                height,

            "fps":
                fps,

            "codec":
                codec,

            "bitrate_mbps":
                bitrate_mbps

        }


    except Exception as error:

        print(
            f"[WARNING] ffprobe error: "
            f"{error}"
        )

        return {}


# ============================================================
# FIND MEDIA
# ============================================================

def find_media_files():

    if not MEDIA_DIR.exists():

        MEDIA_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        return []


    files = []


    for file_path in (
        MEDIA_DIR.rglob("*")
    ):

        if not file_path.is_file():

            continue


        if file_path.suffix.lower() in {

            ".mp4",

            ".jpg",

            ".jpeg"

        }:

            files.append(
                file_path
            )


    files.sort(

        key=lambda path:
        path.stat().st_mtime

    )


    return files


# ============================================================
# DELETE AFTER SUCCESS
# ============================================================

def delete_uploaded_file(
    file_path
):

    try:

        if file_path.exists():

            file_path.unlink()


            print(
                "[DELETE] Removed "
                "local file:"
            )

            print(
                file_path
            )

            send_event(
                source="uploader",
                event_type="local_file_deleted",
                message="Local file deleted after successful upload",
                camera_id=get_camera_id(file_path),
                filename=file_path.name
            )


        else:

            print(
                "[DELETE] File already "
                "removed."
            )


        return True


    except Exception as error:

        print(
            f"[DELETE] Failed to "
            f"remove file: {error}"
        )

        return False


# ============================================================
# UPLOAD FILE
# ============================================================

def upload_file(
    file_path
):

    global total_uploaded_bytes

    global total_uploaded_files


    camera_id = get_camera_id(
        file_path
    )


    if camera_id is None:

        print(
            "[ERROR] Could not determine "
            f"camera ID: {file_path}"
        )

        return False


    media_type = get_media_type(
        file_path
    )


    if media_type is None:

        print(
            "[ERROR] Unsupported media:"
        )

        print(
            file_path
        )

        return False


    try:

        file_size = (

            file_path
            .stat()
            .st_size

        )


        print()
        print(
            "----------------------------------------"
        )

        print(
            "UPLOADING MEDIA"
        )

        print(
            "----------------------------------------"
        )

        print(
            f"Camera : {camera_id}"
        )

        print(
            f"Type   : {media_type}"
        )

        print(
            f"File   : {file_path}"
        )

        print(
            f"Size   : "
            f"{format_bytes(file_size)}"
        )

        print(
            f"Server : {UPLOAD_URL}"
        )

        send_event(
            source="uploader",
            event_type="upload_started",
            message="Upload started",
            camera_id=camera_id,
            filename=file_path.name
        )


        # ====================================================
        # METADATA
        # ====================================================

        metadata = {}


        if media_type == "video":

            metadata = (
                get_video_metadata(
                    file_path,
                    camera_id
                )
            )


            if metadata:

                print()

                print(
                    "[INFO] Video metadata:"
                )

                print(
                    f"Resolution : "
                    f"{metadata.get('resolution')}"
                )

                print(
                    f"FPS        : "
                    f"{metadata.get('fps')}"
                )

                print(
                    f"Codec      : "
                    f"{metadata.get('codec')}"
                )

                print(
                    f"Duration   : "
                    f"{metadata.get('duration')}"
                )


        # ====================================================
        # SEND
        # ====================================================

        print()

        print(
            "[INFO] Sending..."
        )


        start_time = (
            time.perf_counter()
        )


        with open(
            file_path,
            "rb"
        ) as media_file:


            files = {

                "file": (

                    file_path.name,

                    media_file,

                    (
                        "video/mp4"

                        if media_type == "video"

                        else

                        "image/jpeg"
                    )

                )

            }


            data = {

                "camera_id":
                    camera_id,

                "raspi_mac":
                    RASPI_MAC,

                "media_type":
                    media_type,

                "metadata":
                    json.dumps(
                        metadata
                    )

            }


            response = requests.post(

                UPLOAD_URL,

                data=data,

                files=files,

                timeout=(

                    10,

                    600

                )

            )


        elapsed = (

            time.perf_counter()
            - start_time

        )


        # ====================================================
        # CHECK SERVER RESPONSE
        # ====================================================

        print()

        print(
            f"[INFO] Server response: "
            f"{response.status_code}"
        )


        if response.status_code != 200:

            print(
                "[ERROR] Server rejected "
                "file."
            )

            print(
                response.text
            )

            send_event(
                source="uploader",
                event_type="upload_failed",
                message=f"Server rejected file (HTTP {response.status_code})",
                camera_id=camera_id,
                filename=file_path.name
            )

            return False


        try:

            result = (
                response.json()
            )

        except ValueError:

            print(
                "[ERROR] Server returned "
                "invalid JSON."
            )

            print(
                response.text
            )

            send_event(
                source="uploader",
                event_type="upload_failed",
                message="Server returned invalid JSON",
                camera_id=camera_id,
                filename=file_path.name
            )

            return False


        # ====================================================
        # IMPORTANT
        # ONLY DELETE AFTER SUCCESS
        # ====================================================

        if result.get(
            "status"
        ) != "success":

            print(
                "[ERROR] Server did not "
                "confirm successful upload."
            )

            print(
                response.text
            )

            send_event(
                source="uploader",
                event_type="upload_failed",
                message="Server did not confirm successful upload",
                camera_id=camera_id,
                filename=file_path.name
            )

            return False


        # ====================================================
        # SUCCESS
        # ====================================================

        total_uploaded_bytes += (
            file_size
        )

        total_uploaded_files += 1


        speed_mbps = (

            file_size
            * 8
            / elapsed
            / 1_000_000

            if elapsed > 0

            else 0

        )


        print()
        print(
            "========================================"
        )

        print(
            "         UPLOAD SUCCESS"
        )

        print(
            "========================================"
        )

        print(
            f"Camera       : "
            f"{camera_id}"
        )

        print(
            f"File         : "
            f"{file_path.name}"
        )

        print(
            f"File size    : "
            f"{format_bytes(file_size)}"
        )

        print(
            f"Upload time  : "
            f"{elapsed:.2f} seconds"
        )

        print(
            f"Upload speed : "
            f"{speed_mbps:.2f} Mbps"
        )

        print(
            "========================================"
        )

        send_event(
            source="uploader",
            event_type="upload_success",
            message="Upload successful",
            camera_id=camera_id,
            filename=file_path.name
        )


        # ====================================================
        # DELETE LOCAL FILE
        # ====================================================

        if DELETE_AFTER_UPLOAD:

            print(
                "[DELETE] Server confirmed "
                "successful upload."
            )

            delete_uploaded_file(
                file_path
            )

        else:

            print(
                "[DELETE] Disabled in JSON."
            )

            print(
                "[DELETE] Local file kept."
            )


        return True


    except requests.exceptions.ConnectionError:

        print(
            "[ERROR] Server unreachable."
        )

        print(
            "[INFO] Local file kept "
            "for retry."
        )

        send_event(
            source="uploader",
            event_type="upload_failed",
            message="Server unreachable; file kept for retry",
            camera_id=camera_id,
            filename=file_path.name
        )

        return False


    except requests.exceptions.Timeout:

        print(
            "[ERROR] Upload timeout."
        )

        print(
            "[INFO] Local file kept "
            "for retry."
        )

        send_event(
            source="uploader",
            event_type="upload_failed",
            message="Upload timeout; file kept for retry",
            camera_id=camera_id,
            filename=file_path.name
        )

        return False


    except FileNotFoundError:

        print(
            "[ERROR] File disappeared:"
        )

        print(
            file_path
        )

        send_event(
            source="uploader",
            event_type="upload_failed",
            message="File disappeared before upload completed",
            camera_id=camera_id,
            filename=file_path.name
        )

        return False


    except Exception as error:

        print(
            f"[ERROR] Upload error: "
            f"{error}"
        )

        print(
            "[INFO] Local file kept "
            "for retry."
        )

        send_event(
            source="uploader",
            event_type="upload_failed",
            message=f"Upload error: {error}",
            camera_id=camera_id,
            filename=file_path.name
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("========================================")
    print("       MULTICAM MEDIA UPLOADER")
    print("========================================")

    print(f"Config          : {CONFIG_FILE}")
    print(f"Media directory : {MEDIA_DIR}")
    print(f"Server          : {UPLOAD_URL}")
    print(f"Check interval  : {CHECK_INTERVAL}s")
    print(f"Stable time     : {FILE_STABLE_TIME}s")
    print(f"Delete after OK : {DELETE_AFTER_UPLOAD}")

    print("========================================")

    server_state = None

    while True:

        try:

            available, latency = check_server()

            # =================================================
            # SERVER OFFLINE
            # =================================================

            if not available:

                if server_state is not False:

                    print()

                    print(
                        "[SERVER] Laptop server "
                        "is OFFLINE."
                    )

                    print(
                        "[SERVER] Files will "
                        "remain on Raspberry Pi."
                    )

                    send_event(
                        source="uploader",
                        event_type="server_offline",
                        message="Laptop FastAPI server is offline"
                    )

                server_state = False

                time.sleep(CHECK_INTERVAL)

                continue

            # =================================================
            # SERVER ONLINE
            # =================================================

            if server_state is not True:

                print()

                print(
                    "[SERVER] Laptop server "
                    "is ONLINE."
                )

                send_event(
                    source="uploader",
                    event_type="server_online",
                    message="Laptop FastAPI server is online"
                )

            server_state = True

            if latency is not None:

                print(
                    f"[NETWORK] Health latency: "
                    f"{latency:.2f} ms"
                )

            # =================================================
            # FIND MEDIA
            # =================================================

            media_files = find_media_files()

            # =================================================
            # UPLOAD MEDIA
            # =================================================

            for file_path in media_files:

                print()

                print(
                    f"[INFO] Media found: "
                    f"{file_path.name}"
                )

                send_event(
                    source="uploader",
                    event_type="media_found",
                    message="Media file found and waiting for upload",
                    camera_id=get_camera_id(file_path),
                    filename=file_path.name
                )

                if not is_file_stable(file_path):

                    print(
                        "[INFO] File is still "
                        "being written."
                    )

                    continue

                success = upload_file(file_path)

                if not success:

                    print(
                        "[INFO] Upload failed."
                    )

                    print(
                        "[INFO] Will retry later."
                    )

                    break

            time.sleep(CHECK_INTERVAL)

        # =====================================================
        # KEYBOARD INTERRUPT
        # =====================================================

        except KeyboardInterrupt:

            print()

            print("========================================")
            print("          UPLOADER STATISTICS")
            print("========================================")

            print(
                f"Files uploaded : "
                f"{total_uploaded_files}"
            )

            print(
                f"Total data     : "
                f"{format_bytes(total_uploaded_bytes)}"
            )

            print("========================================")

            print("[INFO] Uploader stopped.")

            break

        # =====================================================
        # OTHER ERRORS
        # =====================================================

        except Exception as error:

            print()

            print(
                f"[ERROR] Main loop error: "
                f"{error}"
            )

            time.sleep(CHECK_INTERVAL)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()





