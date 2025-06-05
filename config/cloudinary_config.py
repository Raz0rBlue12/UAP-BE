import cloudinary
import cloudinary.uploader
import cloudinary.api
from dotenv import load_dotenv
import os

load_dotenv()

# Cloudinary configuration
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True  # Use HTTPS
)

# Default upload options
DEFAULT_UPLOAD_OPTIONS = {
    "resource_type": "auto",  # Automatically detect resource type
    "allowed_formats": ["jpg", "jpeg", "png", "gif", "webp"],  # Allowed image formats
    "max_file_size": 10 * 1024 * 1024,  # 10MB max file size
    "folder": "uap_ecommerce",  # Default folder in Cloudinary
    "transformation": [
        {"width": 1000, "crop": "limit"},  # Limit width to 1000px
        {"quality": "auto"},  # Automatic quality optimization
        {"fetch_format": "auto"}  # Automatic format optimization
    ]
}

def upload_image(file, folder="profiles", **options):
    """
    Upload an image to Cloudinary with secure defaults
    
    Args:
        file: The file to upload
        folder: The folder in Cloudinary to upload to
        **options: Additional upload options
    
    Returns:
        dict: The upload response from Cloudinary
    """
    try:
        # Merge default options with provided options
        upload_options = DEFAULT_UPLOAD_OPTIONS.copy()
        upload_options.update(options)
        upload_options["folder"] = f"uap_ecommerce/{folder}"
        
        # Upload the file
        result = cloudinary.uploader.upload(
            file,
            **upload_options
        )
        
        return {
            "url": result["secure_url"],
            "public_id": result["public_id"],
            "format": result["format"],
            "width": result["width"],
            "height": result["height"],
            "bytes": result["bytes"]
        }
    except Exception as e:
        raise Exception(f"Failed to upload image: {str(e)}")

def delete_image(public_id):
    """
    Delete an image from Cloudinary
    
    Args:
        public_id: The public ID of the image to delete
    """
    try:
        return cloudinary.uploader.destroy(public_id)
    except Exception as e:
        raise Exception(f"Failed to delete image: {str(e)}") 