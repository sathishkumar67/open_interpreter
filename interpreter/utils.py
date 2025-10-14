from __future__ import annotations
import os
import mss
from datetime import datetime

def take_screenshot() -> str:
    """
    Captures a screenshot of the primary monitor and saves it to the 'screenshots' directory.

    This function uses the `mss` library to capture the screen and saves the screenshot as a PNG file
    in the 'screenshots' directory. The file is named with a timestamp to ensure uniqueness.

    Returns:
        str: The file path of the saved screenshot.
    """
    # Ensure the 'screenshots' directory exists; create it if it doesn't
    if not os.path.exists("screenshots"):
        os.makedirs("screenshots")

    # Create a screen capture object using mss
    with mss.mss() as sct:
        # Select the primary monitor (index 1 in mss)
        monitor = sct.monitors[1]
        # Capture the screen contents of the primary monitor
        screenshot = sct.grab(monitor)

        # Generate a timestamped filename for the screenshot
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join("screenshots", f"screenshot_{ts}.png")

        # Save the screenshot as a PNG file
        mss.tools.to_png(screenshot.rgb, screenshot.size, output=path)

        # Return the file path of the saved screenshot
        return path