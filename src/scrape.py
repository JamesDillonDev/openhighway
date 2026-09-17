import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import BASE_URL, OUTPUT_FILE, START_ID, END_ID, WORKERS, USER_AGENT

session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT
})


def get_camera(camera_id):
    camera_id = f"{camera_id:05d}"

    html_url = f"{BASE_URL}/html/{camera_id}.html"
    image_url = f"{BASE_URL}/images/{camera_id}.jpg"

    try:
        # ---------------------------------------------------------
        # 1. Check the JPG FIRST
        # ---------------------------------------------------------

        image = session.get(
            image_url,
            timeout=10,
            stream=True
        )

        if image.status_code != 200:
            return None

        content_type = image.headers.get(
            "Content-Type",
            ""
        ).lower()

        if not content_type.startswith("image/"):
            return None

        # ---------------------------------------------------------
        # 2. Get camera information
        # ---------------------------------------------------------

        page = session.get(
            html_url,
            timeout=10
        )

        if page.status_code != 200:
            return None

        soup = BeautifulSoup(
            page.text,
            "html.parser"
        )

        text = soup.get_text(
            " ",
            strip=True
        )

        # ---------------------------------------------------------
        # 3. Extract camera description
        # ---------------------------------------------------------

        description = None

        match = re.search(
            r"Camera:\s*(\d+)\s*-\s*(.*?)(?:Refresh|$)",
            text,
            re.IGNORECASE
        )

        if match:
            description = match.group(2).strip()

        # ---------------------------------------------------------
        # 4. Extract carriageway/direction
        # ---------------------------------------------------------

        carriageway = None

        match = re.search(
            r"carriageway closest to the camera is\s+(.*?)(?:\.|$)",
            text,
            re.IGNORECASE
        )

        if match:
            carriageway = match.group(1).strip()

        # ---------------------------------------------------------
        # 5. Return camera
        # ---------------------------------------------------------

        return {
            "id": camera_id,
            "description": description,
            "carriageway": carriageway,
            "image_url": image_url,
            "page_url": html_url
        }

    except requests.RequestException:
        return None


def main():

    cameras = []

    total = END_ID - START_ID + 1

    print(
        f"Scanning {total:,} possible camera IDs..."
    )

    with ThreadPoolExecutor(
        max_workers=WORKERS
    ) as executor:

        futures = {
            executor.submit(
                get_camera,
                camera_id
            ): camera_id
            for camera_id in range(
                START_ID,
                END_ID + 1
            )
        }

        completed = 0

        for future in as_completed(futures):

            completed += 1

            result = future.result()

            # Only add cameras whose JPG exists
            if result:

                cameras.append(result)

                print(
                    f"[FOUND] "
                    f"{result['id']} | "
                    f"{result['description']}"
                )

            if completed % 1000 == 0:

                print(
                    f"Progress: "
                    f"{completed:,}/{total:,} "
                    f"({completed / total * 100:.1f}%)"
                )

    # Sort cameras numerically
    cameras.sort(
        key=lambda camera: int(camera["id"])
    )

    # ---------------------------------------------------------
    # JSON metadata
    # ---------------------------------------------------------

    output = {
        "last_updated": datetime.now(
            timezone.utc
        ).isoformat(),

        "source": "National Highways",

        "camera_count": len(cameras),

        "cameras": cameras
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False
        )

    print()
    print(
        f"Found {len(cameras):,} available cameras."
    )

    print(
        f"Saved to: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()