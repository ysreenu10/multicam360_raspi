
#!/usr/bin/env python3

import json
import os
import select
import signal
import subprocess
import sys
import threading
import time

from datetime import datetime
from pathlib import Path

import RPi.GPIO as GPIO

# Dashboard event reporting
from multicam_event import send_event


# ============================================================
# CONFIGURATION
# ============================================================

CONFIG_FILE = Path(
    "/home/raspi5/multicam_config.json"
)


# ============================================================
# GPIO
# ============================================================

VIDEO_BUTTON = 17
IMAGE_BUTTON = 27

GPIO.setmode(GPIO.BCM)

GPIO.setup(
    VIDEO_BUTTON,
    GPIO.IN,
    pull_up_down=GPIO.PUD_UP
)

GPIO.setup(
    IMAGE_BUTTON,
    GPIO.IN,
    pull_up_down=GPIO.PUD_UP
)


# ============================================================
# LOAD CONFIGURATION
# ============================================================

def load_config():

    if not CONFIG_FILE.exists():

        raise FileNotFoundError(
            f"Config file not found: {CONFIG_FILE}"
        )

    with open(
        CONFIG_FILE,
        "r"
    ) as file:

        config = json.load(file)

    if not config.get("cameras"):

        raise ValueError(
            "No cameras configured."
        )

    return config


CONFIG = load_config()


BASE_DIR = Path(
    CONFIG["storage"]["base_dir"]
)

CAMERAS = CONFIG["cameras"]


# ============================================================
# GLOBAL
# ============================================================

gst_processes = {}

operation_lock = threading.Lock()

button_running = True


# ============================================================
# CAMERA LOOKUP
# ============================================================

def get_camera(camera_id):

    for camera in CAMERAS:

        if camera["camera_id"] == camera_id:

            return camera

    return None


# ============================================================
# DATE FOLDER
# ============================================================

def get_date_folder():

    return datetime.now().strftime(
        "%Y-%m-%d"
    )


# ============================================================
# VIDEO DIRECTORY
# ============================================================

def get_video_dir(camera_id):

    directory = (

        BASE_DIR

        / camera_id

        / get_date_folder()

        / "videos"

    )

    directory.mkdir(
        parents=True,
        exist_ok=True
    )

    return directory


# ============================================================
# IMAGE DIRECTORY
# ============================================================

def get_image_dir(camera_id):

    directory = (

        BASE_DIR

        / camera_id

        / get_date_folder()

        / "images"

    )

    directory.mkdir(
        parents=True,
        exist_ok=True
    )

    return directory


# ============================================================
# CHECK ONE CAMERA
# ============================================================

def is_camera_recording(camera_id):

    process = gst_processes.get(
        camera_id
    )

    if process is None:

        return False

    if process.poll() is None:

        return True

    gst_processes[camera_id] = None

    return False


# ============================================================
# CHECK ANY CAMERA
# ============================================================

def is_recording():

    for camera in CAMERAS:

        if is_camera_recording(
            camera["camera_id"]
        ):

            return True

    return False


# ============================================================
# BUILD VIDEO PIPELINE
# ============================================================

def build_video_pipeline(camera):

    camera_id = camera["camera_id"]

    device = camera["device"]

    video = camera["video"]

    width = int(
        video["width"]
    )

    height = int(
        video["height"]
    )

    camera_fps = int(
        video["camera_fps"]
    )

    record_fps = int(
        video["record_fps"]
    )

    segment_seconds = int(
        video["segment_seconds"]
    )

    bitrate = int(
        video["bitrate_kbps"]
    )

    input_format = video.get(
        "input_format",
        "MJPG"
    ).upper()


    video_dir = get_video_dir(
        camera_id
    )


    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )


    location = str(

        video_dir

        / (
            f"{camera_id}_"
            f"{timestamp}_"
            "%05d.mp4"
        )

    )


    command = [

        "gst-launch-1.0",

        "-e",

        "v4l2src",

        f"device={device}"

    ]


    # ========================================================
    # INPUT FORMAT
    # ========================================================

    if input_format == "MJPG":

        command += [

            "!",

            (
                f"image/jpeg,"
                f"width={width},"
                f"height={height},"
                f"framerate={camera_fps}/1"
            ),

            "!",

            "jpegdec"

        ]


    elif input_format in (
        "YUYV",
        "YUY2"
    ):

        command += [

            "!",

            (
                f"video/x-raw,"
                f"format=YUY2,"
                f"width={width},"
                f"height={height},"
                f"framerate={camera_fps}/1"
            )

        ]


    else:

        raise ValueError(

            f"{camera_id}: "
            f"unsupported input format "
            f"'{input_format}'"

        )


    # ========================================================
    # COMMON PIPELINE
    # ========================================================

    command += [

        "!",

        "videoconvert",

        "!",

        "videorate",

        "!",

        (
            f"video/x-raw,"
            f"framerate={record_fps}/1"
        ),

        "!",

        "x264enc",

        "tune=zerolatency",

        "speed-preset=veryfast",

        f"bitrate={bitrate}",

        "key-int-max=1",

        "!",

        "h264parse",

        "!",

        "splitmuxsink",

        f"location={location}",

        (
            f"max-size-time="
            f"{segment_seconds * 1000000000}"
        ),

        "muxer-factory=mp4mux"

    ]


    return command, location


# ============================================================
# START ONE CAMERA
# ============================================================

def start_camera(camera):

    camera_id = camera["camera_id"]

    device = camera["device"]


    if is_camera_recording(
        camera_id
    ):

        print(
            f"[INFO] {camera_id} "
            f"is already recording."
        )

        return True


    if not os.path.exists(device):

        print(
            f"[ERROR] {camera_id} "
            f"device not found:"
        )

        print(device)

        return False


    try:

        command, location = (
            build_video_pipeline(
                camera
            )
        )


        video = camera["video"]


        print()
        print(
            "========================================"
        )

        print(
            "       STARTING CAMERA RECORDING"
        )

        print(
            "========================================"
        )

        print(
            f"Camera ID   : "
            f"{camera_id}"
        )

        print(
            f"Name        : "
            f"{camera.get('name', '')}"
        )

        print(
            f"Device      : "
            f"{device}"
        )

        print(
            f"Resolution  : "
            f"{video['width']}x"
            f"{video['height']}"
        )

        print(
            f"Input FPS   : "
            f"{video['camera_fps']}"
        )

        print(
            f"Record FPS  : "
            f"{video['record_fps']}"
        )

        print(
            f"Segment     : "
            f"{video['segment_seconds']} seconds"
        )

        print(
            f"Bitrate     : "
            f"{video['bitrate_kbps']} kbps"
        )

        print(
            f"Format      : "
            f"{video.get('input_format')}"
        )

        print(
            f"Output      : "
            f"{location}"
        )

        print(
            "========================================"
        )


        process = subprocess.Popen(
            command
        )


        gst_processes[
            camera_id
        ] = process


        time.sleep(2)


        if process.poll() is not None:

            print(
                f"[ERROR] {camera_id} "
                f"GStreamer stopped."
            )

            gst_processes[
                camera_id
            ] = None

            return False


        print(
            f"[INFO] {camera_id} "
            f"recording started."
        )

        # Send a non-critical dashboard event.
        # Failure to reach the laptop must not stop recording.
        send_event(
            source="camera",
            event_type="video_recording_started",
            message=f"{camera_id} video recording started",
            camera_id=camera_id
        )

        return True


    except Exception as error:

        print(
            f"[ERROR] Failed to start "
            f"{camera_id}: {error}"
        )

        gst_processes[
            camera_id
        ] = None

        return False


# ============================================================
# START ALL CAMERAS
# ============================================================

def start_recording():

    with operation_lock:

        started = 0


        for camera in CAMERAS:

            if start_camera(camera):

                started += 1


        print(
            f"[INFO] Recording started "
            f"for {started}/"
            f"{len(CAMERAS)} cameras."
        )


# ============================================================
# STOP ONE CAMERA
# ============================================================

def stop_camera(camera):

    camera_id = camera["camera_id"]

    process = gst_processes.get(
        camera_id
    )


    if (

        process is None

        or process.poll() is not None

    ):

        gst_processes[
            camera_id
        ] = None

        return


    print(
        f"[INFO] Stopping "
        f"{camera_id}..."
    )


    try:

        process.send_signal(
            signal.SIGINT
        )


        process.wait(
            timeout=15
        )


    except subprocess.TimeoutExpired:

        print(
            f"[WARNING] "
            f"{camera_id} did not stop."
        )


        process.terminate()


        try:

            process.wait(
                timeout=5
            )


        except subprocess.TimeoutExpired:

            print(
                f"[WARNING] Killing "
                f"{camera_id}..."
            )

            process.kill()

            process.wait()


    except Exception as error:

        print(
            f"[ERROR] Error stopping "
            f"{camera_id}: {error}"
        )


    finally:

        gst_processes[
            camera_id
        ] = None

        # Notify dashboard that this camera recording stopped.
        send_event(
            source="camera",
            event_type="video_recording_stopped",
            message=f"{camera_id} video recording stopped",
            camera_id=camera_id
        )


# ============================================================
# STOP ALL CAMERAS
# ============================================================

def stop_recording():

    with operation_lock:

        if not is_recording():

            print(
                "[INFO] Recording is not running."
            )

            return


        for camera in CAMERAS:

            stop_camera(
                camera
            )


        print(
            "[INFO] All recordings stopped."
        )


# ============================================================
# SNAPSHOT - MJPEG
# ============================================================

def snapshot_mjpeg(
    camera,
    output_file,
    settings
):

    device = camera["device"]

    width = int(
        settings["width"]
    )

    height = int(
        settings["height"]
    )

    fps = int(
        settings.get(
            "fps",
            30
        )
    )


    command = [

        "gst-launch-1.0",

        "-e",

        "v4l2src",

        f"device={device}",

        "num-buffers=1",

        "!",

        (
            f"image/jpeg,"
            f"width={width},"
            f"height={height},"
            f"framerate={fps}/1"
        ),

        "!",

        "filesink",

        f"location={output_file}"

    ]


    result = subprocess.run(

        command,

        timeout=10

    )


    return (
        result.returncode == 0
    )


# ============================================================
# SNAPSHOT - YUY2 WARMUP
# ============================================================

def snapshot_yuy2_warmup(
    camera,
    output_file,
    settings
):

    device = camera["device"]

    width = int(
        settings["width"]
    )

    height = int(
        settings["height"]
    )

    fps = int(
        settings.get(
            "fps",
            30
        )
    )

    warmup_frames = int(
        settings.get(
            "warmup_frames",
            30
        )
    )

    min_file_size = int(
        settings.get(
            "min_file_size",
            10000
        )
    )


    temp_dir = (
        output_file.parent
        / ".snapshot_temp"
    )


    temp_dir.mkdir(
        parents=True,
        exist_ok=True
    )


    pattern = (
        temp_dir
        / "frame_%03d.jpg"
    )


    command = [

        "gst-launch-1.0",

        "-e",

        "v4l2src",

        f"device={device}",

        "io-mode=mmap",

        f"num-buffers={warmup_frames}",

        "!",

        (
            f"video/x-raw,"
            f"format=YUY2,"
            f"width={width},"
            f"height={height},"
            f"framerate={fps}/1"
        ),

        "!",

        "videoconvert",

        "!",

        "jpegenc",

        "!",

        "multifilesink",

        f"location={pattern}",

        "index=0"

    ]


    try:

        result = subprocess.run(

            command,

            timeout=15

        )


        if result.returncode != 0:

            return False


        frames = sorted(
            temp_dir.glob(
                "frame_*.jpg"
            )
        )


        if not frames:

            return False


        selected = frames[-1]


        size = selected.stat().st_size


        if size < min_file_size:

            print(
                f"[ERROR] Snapshot too small: "
                f"{size} bytes"
            )

            return False


        selected.replace(
            output_file
        )


        return True


    finally:

        for frame in temp_dir.glob(
            "frame_*.jpg"
        ):

            try:

                frame.unlink()

            except FileNotFoundError:

                pass


# ============================================================
# SNAPSHOT ALL CAMERAS
# ============================================================

def take_snapshot():

    with operation_lock:

        for camera in CAMERAS:

            camera_id = (
                camera["camera_id"]
            )

            settings = camera.get(
                "snapshot",
                {}
            )


            method = settings.get(
                "method",
                "mjpeg"
            ).lower()


            if not os.path.exists(
                camera["device"]
            ):

                print(
                    f"[ERROR] {camera_id} "
                    f"device not found."
                )

                continue


            image_dir = get_image_dir(
                camera_id
            )


            timestamp = (
                datetime.now()
                .strftime(
                    "%Y%m%d_%H%M%S_%f"
                )[:-3]
            )


            output_file = (

                image_dir

                / (
                    f"{camera_id}_"
                    f"{timestamp}.jpg"
                )

            )


            print()
            print(
                "========================================"
            )

            print(
                "          CAPTURING SNAPSHOT"
            )

            print(
                "========================================"
            )

            print(
                f"Camera : {camera_id}"
            )

            print(
                f"Method : {method}"
            )

            print(
                f"Device : "
                f"{camera['device']}"
            )

            print(
                f"Output : "
                f"{output_file}"
            )

            print(
                "========================================"
            )


            try:

                if method == (
                    "yuy2_warmup"
                ):

                    success = (
                        snapshot_yuy2_warmup(
                            camera,
                            output_file,
                            settings
                        )
                    )


                elif method == "mjpeg":

                    success = (
                        snapshot_mjpeg(
                            camera,
                            output_file,
                            settings
                        )
                    )


                else:

                    print(
                        f"[ERROR] Unknown "
                        f"snapshot method: "
                        f"{method}"
                    )

                    continue


                if (

                    success

                    and output_file.exists()

                ):

                    size = (
                        output_file
                        .stat()
                        .st_size
                    )


                    print(
                        f"[SUCCESS] "
                        f"{camera_id} "
                        f"snapshot captured."
                    )

                    print(
                        f"[INFO] Size: "
                        f"{size / 1024:.2f} KB"
                    )

                    send_event(
                        source="camera",
                        event_type="snapshot_captured",
                        message=f"{camera_id} snapshot captured successfully",
                        camera_id=camera_id,
                        filename=output_file.name
                    )


                else:

                    print(
                        f"[ERROR] "
                        f"{camera_id} "
                        f"snapshot failed."
                    )

                    send_event(
                        source="camera",
                        event_type="snapshot_failed",
                        message=f"{camera_id} snapshot failed",
                        camera_id=camera_id
                    )


            except (
                subprocess.TimeoutExpired
            ):

                print(
                    f"[ERROR] "
                    f"{camera_id} "
                    f"snapshot timeout."
                )

                send_event(
                    source="camera",
                    event_type="snapshot_failed",
                    message=f"{camera_id} snapshot timeout",
                    camera_id=camera_id
                )


            except Exception as error:

                print(
                    f"[ERROR] "
                    f"{camera_id} "
                    f"snapshot error: "
                    f"{error}"
                )

                send_event(
                    source="camera",
                    event_type="snapshot_failed",
                    message=f"{camera_id} snapshot error",
                    camera_id=camera_id
                )


# ============================================================
# STATUS
# ============================================================

def show_status():

    print()
    print(
        "========================================"
    )

    print(
        "             CAMERA STATUS"
    )

    print(
        "========================================"
    )


    for camera in CAMERAS:

        camera_id = (
            camera["camera_id"]
        )

        status = (

            "RUNNING"

            if is_camera_recording(
                camera_id
            )

            else

            "STOPPED"

        )


        print(
            f"{camera_id:8} : "
            f"{status}"
        )

        print(
            f"  Device : "
            f"{camera['device']}"
        )


    print(
        "========================================"
    )


# ============================================================
# BUTTON MONITOR
# ============================================================

def button_monitor():

    global button_running


    print()
    print(
        "[BUTTON] Button monitor started."
    )

    print(
        "[BUTTON] GPIO17 / Pin 11 = Video"
    )

    print(
        "[BUTTON] GPIO27 / Pin 13 = Image"
    )


    last_video_state = GPIO.HIGH

    last_image_state = GPIO.HIGH


    try:

        while button_running:

            video_state = GPIO.input(
                VIDEO_BUTTON
            )

            image_state = GPIO.input(
                IMAGE_BUTTON
            )


            # =================================================
            # VIDEO BUTTON
            # =================================================

            if (

                last_video_state
                == GPIO.HIGH

                and

                video_state
                == GPIO.LOW

            ):

                if is_recording():

                    print(
                        "[BUTTON] "
                        "Video -> STOP"
                    )

                    stop_recording()

                else:

                    print(
                        "[BUTTON] "
                        "Video -> START"
                    )

                    start_recording()


                time.sleep(
                    0.3
                )


            # =================================================
            # IMAGE BUTTON
            # =================================================

            if (

                last_image_state
                == GPIO.HIGH

                and

                image_state
                == GPIO.LOW

            ):

                print(
                    "[BUTTON] "
                    "Image -> SNAPSHOT"
                )


                take_snapshot()


                time.sleep(
                    0.3
                )


            last_video_state = (
                video_state
            )

            last_image_state = (
                image_state
            )


            time.sleep(
                0.05
            )


    except Exception as error:

        if button_running:

            print(
                f"[BUTTON] Error: "
                f"{error}"
            )


# ============================================================
# MAIN
# ============================================================

def main():

    global button_running


    print()
    print(
        "========================================"
    )

    print(
        "     MULTICAM CAMERA CONTROLLER"
    )

    print(
        "========================================"
    )

    print(
        f"Config  : "
        f"{CONFIG_FILE}"
    )

    print(
        f"Cameras : "
        f"{len(CAMERAS)}"
    )

    print(
        f"Storage : "
        f"{BASE_DIR}"
    )

    print(
        "========================================"
    )


    for camera in CAMERAS:

        print(

            f"{camera['camera_id']} -> "

            f"{camera['device']} -> "

            f"{camera.get('name', '')}"

        )


    button_thread = threading.Thread(

        target=button_monitor,

        daemon=True

    )


    button_thread.start()


    try:

        while True:

            if sys.stdin.isatty():

                ready, _, _ = (
                    select.select(
                        [sys.stdin],
                        [],
                        [],
                        0.2
                    )
                )


                if ready:

                    command = (
                        sys.stdin
                        .readline()
                        .strip()
                        .upper()
                    )


                    if command == "START":

                        start_recording()


                    elif command == "STOP":

                        stop_recording()


                    elif command == "SNAPSHOT":

                        take_snapshot()


                    elif command == "STATUS":

                        show_status()


                    elif command == "QUIT":

                        break


                    elif command:

                        print(
                            "[ERROR] Use "
                            "START, STOP, "
                            "SNAPSHOT, "
                            "STATUS or QUIT."
                        )


            else:

                time.sleep(
                    0.2
                )


    except KeyboardInterrupt:

        print(
            "\n[INFO] Ctrl+C received."
        )


    finally:

        # IMPORTANT:
        # Stop button thread before GPIO cleanup.
        button_running = False

        stop_recording()

        GPIO.cleanup()

        print(
            "[INFO] GPIO cleaned up."
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()







