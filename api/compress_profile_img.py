import logging
from pathlib import Path
from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps  # type: ignore
import io
import time
from fastapi.concurrency import run_in_threadpool


logger = logging.getLogger('users_logger')


async def process_profile_img(profile_file: UploadFile, user_id: int):
    allowed_types = ["image/jpeg", "image/png", "image/webp"]
    MAX_SIZE = 10 * 1024 * 1024

    if profile_file.size and profile_file.size > MAX_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail='Only images up to 10MB allowed!')

    if profile_file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only JPEG, PNG, and WebP images are allowed."
        )

    upload_dir = Path(f"static/uploads/profiles/{user_id}")
    upload_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f'profile process {profile_file}')

    if not profile_file or not profile_file.filename:
        logger.error("Upload attempted without a file")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No file uploaded or filename is missing"
        )
    # Use timestamp + original stem to avoid collisions
    suffix = ".jpg"  # forcing JPEG output
    stem = Path(profile_file.filename or "upload").stem

    new_filename = f"{int(time.time())}_{user_id}_{stem}{suffix}"
    destination_path = upload_dir / new_filename

    # UploadFile read() pulls it into memory
    content = await profile_file.read()

    def transform_and_save(image_bytes, save_path):
        with Image.open(io.BytesIO(initial_bytes=image_bytes)) as img:
            width, height = img.size
            logger.debug(f'Image width{width}')
            if width > 10000 or height > 10000:
                raise HTTPException(
                    status_code=400, detail="Image dimensions too large.")

            # Fix orientation and convert to RGB
            img = ImageOps.exif_transpose(img)

            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # Resize logic (e.g., maintain 3:4 portrait ratio)
            target_width = 800

            if width > target_width:
                w_percent = (target_width / float(width))
                
                target_height = int((float(height) * float(w_percent)))
                
                img = img.resize((target_width, target_height),
                                 Image.Resampling.LANCZOS)

            # Save to a temporary buffer, then use shutil to write to disk
            # This ensures we don't leave a half-written file if the save fails

            img.save(save_path, format="JPEG", optimize=True, quality=85)
    try:
        await run_in_threadpool(transform_and_save, content, destination_path)
        
        logger.info(f'successfully compressed {new_filename}')
        
        return f"uploads/profiles/{user_id}/{new_filename}"

    except Image.DecompressionBombError:
        raise HTTPException(
            status_code=400, detail="Image exceeds safe size limits.")

    except Exception as e:
        logger.error(f'Error while compressing file: {e}')
        raise e
