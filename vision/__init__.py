"""Vision layer: OCR client, template matching, interaction."""

from vision.calibration import CalibrationDB, load_calibration
from vision.ocr_client import OCRClient
from vision.interaction import Interaction

__all__ = ["CalibrationDB", "load_calibration", "OCRClient", "Interaction"]
