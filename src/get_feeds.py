import json
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

CONFIG_DIR = Path("config")

CAMERA_JSON = CONFIG_DIR / "national_highways_cameras.json"

IMAGE_DIR = CONFIG_DIR / "camera_images"

WORKERS = 20

TIMEOUT = 15


# ---------------------------------------------------------
# Setup
# ---------------------------------------------------------

IMAGE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ---------------------------------------------------------
# Load cameras
# ---------------------------------------------------------

with open(
    CAMERA_JSON,
    "r",
    encoding="utf-8"
) as file:

    data = json.load(file)


cameras = data.get(
    "cameras",
    []
)


print(
    f"Found {len(cameras):,} cameras in JSON"
)

print(
    f"Saving images to: {IMAGE_DIR}"
)

print()


# ---------------------------------------------------------
# Download function
# ---------------------------------------------------------

def download_camera(camera):

    camera_id = camera["id"]

    image_url = camera["image_url"]

    output_file = IMAGE_DIR / f"{camera_id}.jpg"

    try:

        response = requests.get(
            image_url,
            timeout=TIMEOUT,
            headers={
                "User-Agent":
                    "National Highways Camera Downloader/1.0"
            }
        )

        if response.status_code != 200:
            return (
                camera_id,
                False,
                f"HTTP {response.status_code}"
            )

        content_type = response.headers.get(
            "Content-Type",
            ""
        ).lower()

        if not content_type.startswith("image/"):
            return (
                camera_id,
                False,
                f"Invalid content type: {content_type}"
            )

        # Save image
        with open(
            output_file,
            "wb"
        ) as file:

            file.write(
                response.content
            )

        return (
            camera_id,
            True,
            output_file
        )

    except requests.RequestException as error:

        return (
            camera_id,
            False,
            str(error)
        )


# ---------------------------------------------------------
# Download cameras
# ---------------------------------------------------------

successful = 0
failed = 0

with ThreadPoolExecutor(
    max_workers=WORKERS
) as executor:

    futures = [
        executor.submit(
            download_camera,
            camera
        )
        for camera in cameras
    ]

    completed = 0

    for future in as_completed(futures):

        completed += 1

        camera_id, success, result = future.result()

        if success:

            successful += 1

            print(
                f"[{completed:,}/{len(cameras):,}] "
                f"[OK] {camera_id}"
            )

        else:

            failed += 1

            print(
                f"[{completed:,}/{len(cameras):,}] "
                f"[FAILED] {camera_id} - {result}"
            )


# ---------------------------------------------------------
# Summary
# ---------------------------------------------------------

print()
print("Download complete")
print("-----------------")

print(
    f"Successful: {successful:,}"
)

print(
    f"Failed:     {failed:,}"
)

print(
    f"Images:     {IMAGE_DIR}"
)