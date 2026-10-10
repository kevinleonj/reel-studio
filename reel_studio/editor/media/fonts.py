"""The one typeface: Poppins Bold, shipped with the package under the SIL OFL (fonts/OFL.txt).

The kit fell back to host fonts (kit common.py:154-165); the product ships its own so a Reel
looks the same on the laptop and in the cloud image.
"""

from pathlib import Path

from PIL import ImageFont

FONT = Path(__file__).parent / "fonts" / "Poppins-Bold.ttf"


def bold(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size)
