import cv2
from paddleocr import PaddleOCR
import re
import logging

logger = logging.getLogger(__name__)

# Load weights locally in PaddleOCR
ocr = PaddleOCR(
    lang='en',
    det_model_dir='src/ai/weights/en_PP-OCRv3_det_infer',
    rec_model_dir='src/ai/weights/en_PP-OCRv4_rec_infer',
    cls_model_dir='src/ai/weights/ch_ppocr_mobile_v2.0_cls_infer',
    use_angle_cls=True
)

def process_frame_for_barcode(frame, bbox):
    """Process the frame with the given bbox and find an 8-digit barcode"""
    try:
        # Crop the image with the provided bbox
        cropped_img = frame[bbox["y_min"]:bbox["y_max"], bbox["x_min"]:bbox["x_max"]]
        
        # Check that the cropped image is not empty
        if cropped_img.size == 0:
            logger.error("The cropped image is empty. Check the coordinates!")
            return None, None

        # Run OCR on the cropped image
        results = ocr.ocr(cropped_img)
        if results is None:
            logger.info("OCR did not find any text.")
            return None, None
        
        # Check that the output is a list and not empty
        if not isinstance(results, list) or len(results) == 0:
            logger.info("No text found in the frame.")
            return None, None
        
        # Extract detected texts
        detected_texts = []
        for block in results:
            if block is None:
                continue
            for line in block:
                if line is None or len(line) < 2:
                    continue
                text = line[1][0]  # Get the text
                detected_texts.append(text)
        
        if not detected_texts:
            logger.info("📭	No valid text extracted from OCR.")
            return None, None
        
        # Combine texts and search for an 8-digit barcode
        full_text = ' '.join(detected_texts)
        numbers = re.findall(r'\d+', full_text)
        for number in numbers:
            if len(number) == 8:
                logger.info(f"🟢 8-digit barcode detection: {number}")
                return number, cropped_img  # Return the barcode and cropped image
        return None, None
    except Exception as e:
        logger.error(f"Error processing frame: {e}")
        return None, None