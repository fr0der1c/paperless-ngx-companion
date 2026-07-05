import unittest
from unittest.mock import patch

import app


class PDFImageConversionTest(unittest.TestCase):
    def test_limits_pdf_size_before_loading_images(self) -> None:
        images = [object()]

        with (
            patch.object(app, "LLM_OCR_IMAGE_MAX_SIZE", 2048),
            patch.object(app, "convert_from_bytes", return_value=images) as convert,
        ):
            result = app._images_from_bytes(b"%PDF-test", "application/pdf")

        self.assertIs(result, images)
        convert.assert_called_once_with(b"%PDF-test", size=2048)

    def test_preserves_unlimited_rendering_when_limit_is_disabled(self) -> None:
        with (
            patch.object(app, "LLM_OCR_IMAGE_MAX_SIZE", 0),
            patch.object(app, "convert_from_bytes", return_value=[]) as convert,
        ):
            app._images_from_bytes(b"%PDF-test", "application/pdf")

        convert.assert_called_once_with(b"%PDF-test", size=None)


if __name__ == "__main__":
    unittest.main()
