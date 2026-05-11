import logging

from fastapi import File, HTTPException, UploadFile, status


logger = logging.getLogger('users_logger')


async def process_profile_img(profile_image: UploadFile = File(...)):
    logger.info(f"processing profile upload {profile_image.filename}")

    allowed_types = ["image/jpeg", "image/png", "image/webp"]
    MAX_SIZE = 10 * 1024 * 1024

    if profile_image.size and profile_image.size > MAX_SIZE:
        logger.error(f"Only images up to 10MB allowed!")
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail='Only images up to 10MB allowed!')

    if profile_image.content_type not in allowed_types:
        logger.error("Only JPEG, PNG, and WebP images are allowed.")
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only JPEG, PNG, and WebP images are allowed."
        )

    if not profile_image or not profile_image.filename:
        logger.error("Upload attempted without a file")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No file uploaded or filename is missing"
        )
    # UploadFile read() pulls it into memory
    try:
        logger.info(f'reading file bytes')
        return await profile_image.read()

    except Exception as e:
        logger.error(f'Error while reading file: {e}')
        raise e

    finally:
        await profile_image.close()
