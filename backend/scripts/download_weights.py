"""Fetch the pretrained EAST text-detector weights (96MB, not committed).
Run once: python scripts/download_weights.py
"""
import os
import urllib.request

URL = "https://raw.githubusercontent.com/oyyd/frozen_east_text_detection.pb/master/frozen_east_text_detection.pb"
DEST = os.path.join(os.path.dirname(__file__), "..", "vision", "weights", "frozen_east_text_detection.pb")

if __name__ == "__main__":
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    if os.path.exists(DEST):
        print(f"Already have weights at {DEST}")
    else:
        print(f"Downloading EAST weights to {DEST} ...")
        urllib.request.urlretrieve(URL, DEST)
        print("Done.")
