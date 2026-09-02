import os
import gc
import time
import threading
import logging
from typing import List
from pathlib import Path

import cv2
import numpy as np
import paddle
from paddleocr import PaddleOCR
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# Disable remote model source probing during PaddleOCR init to avoid startup delays.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# Keep oneDNN primitive cache bounded on CPU workloads.
os.environ.setdefault("ONEDNN_PRIMITIVE_CACHE_CAPACITY", "10")

# Aggressive GC and allocator behavior flags, set before OCR engine creation.
os.environ.setdefault("FLAGS_eager_delete_tensor_gb", "0.0")
os.environ.setdefault("FLAGS_fast_eager_deletion_mode", "True")
os.environ.setdefault("FLAGS_allocator_strategy", "naive_best_fit")

TOKEN = "6846587660:AAFQX323ckFHFxaOODnNMZsPXh7LR4kRIT8"
MIN_SCORE = 0.8
CPU_THREADS = min(os.cpu_count() or 1, 4)
USE_GPU = True

# Telegram message max length is 4096 chars.
TELEGRAM_MAX_MESSAGE_LEN = 4000

ocr = None
_ocr_lock = threading.Lock()
_ocr_init_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("telegram_ocr_bot")


def _build_ocr_engine() -> PaddleOCR:
    # Rely on PaddleOCR's internal logic for GPU usage based on installed packages.
    return PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
def _reinitialize_ocr_engine() -> None:
    global ocr
    with _ocr_init_lock:
        ocr = _build_ocr_engine()


def _predict_with_recovery(image: np.ndarray):
    global ocr
    with _ocr_lock:
        try:
            if hasattr(ocr, "predict"):
                return ocr.predict(image)
            return None
        except RuntimeError as e:
            # Paddle can throw this when predictor state gets unstable.
            if "could not execute a primitive" not in str(e):
                raise
            _reinitialize_ocr_engine()
            gc.collect()
            if hasattr(ocr, "predict"):
                return ocr.predict(image)
            return None


def _extract_text_lines(image: np.ndarray) -> List[str]:
    lines = []

    preds = _predict_with_recovery(image)
    if preds:
        first = preds[0]
        rec_texts = first.get("rec_texts", []) if isinstance(first, dict) else []
        rec_scores = first.get("rec_scores", []) if isinstance(first, dict) else []
        for text, score in zip(rec_texts, rec_scores):
            s = float(score)
            t = str(text).strip()
            if t and s >= MIN_SCORE:
                lines.append(f"{t} (score={s:.2f})")

    # Fallback only if predict output is empty and legacy ocr() exists.
    if lines:
        return lines

    if hasattr(ocr, "ocr"):
        output = ocr.ocr(image, cls=False)
        if output and output[0]:
            for line in output[0]:
                if not line or not isinstance(line, list) or len(line) < 2:
                    continue
                text = str(line[1][0]).strip()
                score = float(line[1][1])
                if text and score >= MIN_SCORE:
                    lines.append(f"{text} (score={score:.2f})")

    return lines


def _save_debug_image(image: np.ndarray, preds, out_dir: str = "test/saved_result") -> str:
    """Draw OCR boxes+text onto the image and save to out_dir. Returns saved path."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    debug_img = image.copy()

    if not preds:
        path = Path(out_dir) / f"full_res_{int(time.time())}.png"
        cv2.imwrite(str(path), debug_img)
        return str(path)

    first = preds[0] if isinstance(preds, (list, tuple)) and len(preds) > 0 else preds

    rec_texts = []
    rec_scores = []
    rec_boxes = []

    if isinstance(first, dict):
        rec_texts = first.get("rec_texts", [])
        rec_scores = first.get("rec_scores", [])
        rec_boxes = first.get("rec_boxes", [])

    # Normalize numpy arrays to Python lists to avoid ambiguous truth-value checks
    if isinstance(rec_texts, np.ndarray):
        rec_texts = rec_texts.tolist()
    if isinstance(rec_scores, np.ndarray):
        rec_scores = rec_scores.tolist()
    if isinstance(rec_boxes, np.ndarray):
        rec_boxes = rec_boxes.tolist()

    # Fallback for older layouts where predict returns sequences of (text, score, box)
    def _is_empty(x):
        if x is None:
            return True
        if isinstance(x, np.ndarray):
            return x.size == 0
        try:
            return len(x) == 0
        except Exception:
            return False

    if _is_empty(rec_boxes) and isinstance(first, (list, tuple, np.ndarray)):
        # try to unpack list entries
        for entry in first:
            if isinstance(entry, dict):
                rec_texts.append(entry.get("rec_texts", ""))
            elif isinstance(entry, (list, tuple)) and len(entry) >= 3:
                rec_texts.append(entry[0])
                rec_scores.append(entry[1])
                rec_boxes.append(entry[2])

    # Draw boxes and labels
    for idx, text in enumerate(rec_texts):
        try:
            score = float(rec_scores[idx]) if idx < len(rec_scores) else None
        except Exception:
            score = None

        box = rec_boxes[idx] if idx < len(rec_boxes) else None
        if box is None:
            continue

        # box may be [[x,y],...]
        try:
            arr = np.array(box, dtype=float)
            if arr.ndim == 2 and arr.shape[1] == 2:
                xs = arr[:, 0]
                ys = arr[:, 1]
                xmin, ymin, xmax, ymax = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
            elif arr.size == 4:
                xmin, ymin, xmax, ymax = map(int, arr.flatten().tolist())
            else:
                continue
        except Exception:
            continue

        cv2.rectangle(debug_img, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
        label = text if isinstance(text, str) else str(text)
        if score is not None:
            label = f"{label} ({score:.2f})"
        cv2.putText(debug_img, label[:40], (xmin, max(0, ymin - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    path = Path(out_dir) / f"full_res_{int(time.time())}.png"
    cv2.imwrite(str(path), debug_img)
    return str(path)


async def _download_photo_as_cv2(update: Update) -> np.ndarray:
    msg = update.effective_message
    if not msg:
        return None

    tg_file = None
    if msg.photo:
        tg_file = await msg.photo[-1].get_file()
    elif msg.document and str(msg.document.mime_type).startswith("image/"):
        tg_file = await msg.document.get_file()

    if not tg_file:
        return None

    data = await tg_file.download_as_bytearray()
    if not data:
        return None

    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return image


async def _send_long_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    if len(text) <= TELEGRAM_MAX_MESSAGE_LEN:
        await context.bot.send_message(chat_id=chat_id, text=text)
        return

    start = 0
    while start < len(text):
        end = min(start + TELEGRAM_MAX_MESSAGE_LEN, len(text))
        await context.bot.send_message(chat_id=chat_id, text=text[start:end])
        start = end


_reinitialize_ocr_engine()


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    await update.effective_message.reply_text(
        "Send me an image and I will run OCR on it and return the extracted text.\n"
        "You can also send /ocr as a caption with the image."
    )


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_t = time.perf_counter()
    chat_id = update.effective_chat.id if update.effective_chat else None
    user = update.effective_user.username if update.effective_user else None
    logger.info("Image message received | chat_id=%s user=%s", chat_id, user)

    try:
        image = await _download_photo_as_cv2(update)
        if image is None:
            logger.warning("Image decode failed | chat_id=%s", chat_id)
            await update.effective_message.reply_text("Could not decode that image. Please send a clearer photo.")
            return

        # Run prediction and build text lines
        preds = _predict_with_recovery(image)
        lines = []
        if preds:
            first = preds[0] if isinstance(preds, (list, tuple)) and len(preds) > 0 else preds
            rec_texts = first.get("rec_texts", []) if isinstance(first, dict) else []
            rec_scores = first.get("rec_scores", []) if isinstance(first, dict) else []
            for text, score in zip(rec_texts, rec_scores):
                s = float(score)
                t = str(text).strip()
                if t and s >= MIN_SCORE:
                    lines.append(f"{t} (score={s:.2f})")
        elapsed = time.perf_counter() - start_t

        if not lines:
            logger.info("OCR done | chat_id=%s lines=0 time=%.2fs", chat_id, elapsed)
            await update.effective_message.reply_text(f"No text found (>= {MIN_SCORE:.2f}). Time: {elapsed:.2f}s")
            return

        result = "OCR Result:\n" + "\n".join(lines)
        result += f"\n\nTotal lines: {len(lines)}\nTime: {elapsed:.2f}s"
        logger.info("OCR done | chat_id=%s lines=%s time=%.2fs", chat_id, len(lines), elapsed)
        # Save and send debug image (if preds available)
        try:
            saved_path = None
            if preds:
                saved_path = _save_debug_image(image, preds)
            if saved_path:
                with open(saved_path, "rb") as fh:
                    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=fh)
        except Exception:
            logger.exception("Failed to save/send debug image | chat_id=%s", chat_id)

        await _send_long_message(context, update.effective_chat.id, result)

    except Exception as e:
        logger.exception("OCR failed | chat_id=%s error=%s", chat_id, e)
        await update.effective_message.reply_text(f"OCR failed: {e}")


async def on_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    await update.effective_message.reply_text("Please send an image (photo).")


async def post_init(app):
    me = await app.bot.get_me()
    logger.info("Bot online | username=@%s id=%s", me.username, me.id)
    logger.info("Waiting for image messages...")


def main() -> None:
    print("python-telegram-bot OCR bot is starting...")
    print("PaddlePaddle:", paddle.__version__)
    print("PaddleOCR will attempt to use GPU:", USE_GPU)
    print("OCR use_gpu requested:", USE_GPU)
    print("Using min OCR score:", MIN_SCORE)

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler(["start", "help"], on_start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo))
    app.add_handler(MessageHandler(filters.ALL, on_other))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
