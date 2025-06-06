from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from typing import List, Optional, Literal
from db.client import get_pg_connection
from models.product import ProductCreate, ProductOut, ProductUpdate, ProductImage
from models.user import UserOut
from routers.auth import get_current_user, require_role
from fastapi import Security
from config.cloudinary_config import upload_image, delete_image
import aiofiles
import os
import tempfile
import magic # for file type validation
import re
from pydantic import BaseModel
import cloudinary
import logging
import json # Import json for parsing image arrays

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/products",
    tags=["Products"]
)

# Security configurations for file uploads
ALLOWED_IMAGE_TYPES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp'
}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB limit for product images

def validate_filename(filename: str) -> bool:
    """Validate filename to prevent path traversal and injection attacks"""
    # Remove any directory components
    filename = os.path.basename(filename)
    # Check for valid characters (alphanumeric, underscore, hyphen, dot)
    return bool(re.match(r'^[a-zA-Z0-9._-]+$', filename))

# Helper function to fetch product with images
async def fetch_product_with_images(conn, product_id: int):
    product = await conn.fetchrow(
        "SELECT * FROM products WHERE product_id = $1",
        product_id
    )
    if not product:
        return None

    images = await conn.fetch(
        "SELECT * FROM product_images WHERE product_id = $1",
        product_id
    )
    product_dict = dict(product)
    product_dict['images'] = [dict(img) for img in images]
    return ProductOut(**product_dict)

# Helper function to fetch product details including images
async def fetch_product_details(conn, product_id: int, user_id: Optional[int] = None):
    query = """
        SELECT
            p.product_id,
            p.seller_id,
            p.name,
            p.description,
            p.price,
            p.stock,
            p.category,
            p.rating,
            p.status,
            p.created_at,
            p.updated_at,
            p.product_type, -- Include product_type
            COALESCE(json_agg(json_build_object(
                'image_id', pi.image_id,
                'image_url', pi.image_url,
                'uploaded_at', pi.uploaded_at
            ) ORDER BY pi.uploaded_at) FILTER (WHERE pi.image_id IS NOT NULL), '[]') as images_json
        FROM products p
        LEFT JOIN product_images pi ON p.product_id = pi.product_id
        WHERE p.product_id = $1
    """
    params = [product_id]

    # Optional filter by seller_id (e.g., for get_seller_products)
    if user_id is not None:
        query += " AND p.seller_id = $2"
        params.append(user_id)

    query += " GROUP BY p.product_id"

    record = await conn.fetchrow(query, *params)

    if not record:
        return None

    # Manually parse the images_json string into a list of ProductImage models
    record_dict = dict(record)
    images_list = json.loads(record_dict.pop('images_json'))
    product_images = [ProductImage(**img) for img in images_list]

    # Create ProductOut model, excluding the raw images_json field
    product = ProductOut(**record_dict, images=product_images)
    return product

@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_data: ProductCreate,
    current_user: UserOut = Depends(require_role(["seller", "admin"]))
):
    """Create a new product (Seller or Admin only)"""
    pool = await get_pg_connection()
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            insert_query = """
                INSERT INTO products (
                    seller_id, name, description, price, stock,
                    category, status, product_type -- Include product_type
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING product_id, seller_id, name, description, price,
                          stock, category, rating, status, created_at, updated_at, product_type -- Include product_type
            """
            new_product_record = await conn.fetchrow(
                insert_query,
                current_user.user_id,
                product_data.name,
                product_data.description,
                product_data.price,
                product_data.stock,
                product_data.category,
                product_data.status,
                product_data.product_type # Pass product_type value
            )

            # Fetch the complete product details including potentially empty images list
            product = await fetch_product_details(conn, new_product_record['product_id'])

            if not product:
                 # Should not happen if insert was successful, but as a safeguard
                 raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch created product details")

            return product

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create product: {e}"
        )
    finally:
        if conn:
            await pool.release(conn)

@router.get("", response_model=List[ProductOut])
async def get_products(
    skip: int = 0,
    limit: int = 10,
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    current_user: Optional[UserOut] = Depends(get_current_user)
):
    """Get all products with optional filters"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Build query with filters
            query = """
                SELECT 
                    p.*,
                    COALESCE(
                        json_agg(
                            json_build_object(
                                'image_id', pi.image_id,
                                'image_url', pi.image_url,
                                'uploaded_at', pi.uploaded_at
                            )
                        ) FILTER (WHERE pi.image_id IS NOT NULL),
                        '[]'::json
                    ) as images
                FROM products p
                LEFT JOIN product_images pi ON p.product_id = pi.product_id
                WHERE p.status = 'approved'
            """
            params = []
            param_count = 1

            if category:
                query += f" AND p.category = ${param_count}"
                params.append(category)
                param_count += 1

            if min_price is not None:
                query += f" AND p.price >= ${param_count}"
                params.append(min_price)
                param_count += 1

            if max_price is not None:
                query += f" AND p.price <= ${param_count}"
                params.append(max_price)
                param_count += 1

            query += " GROUP BY p.product_id"
            query += f" ORDER BY p.created_at DESC LIMIT ${param_count} OFFSET ${param_count + 1}"
            params.extend([limit, skip])

            products = await conn.fetch(query, *params)
            
            # Convert records to dictionaries and parse images
            result = []
            for product in products:
                product_dict = dict(product)
                if isinstance(product_dict['images'], str):
                    import json
                    product_dict['images'] = json.loads(product_dict['images'])
                result.append(product_dict)
            
            return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.get("/seller", response_model=List[ProductOut])
async def get_seller_products(
    current_user: UserOut = Depends(require_role(["seller", "admin"]))
):
    """Get all products for the current seller (Seller or Admin only)"""
    pool = await get_pg_connection()
    conn = None
    try:
        conn = await pool.acquire()

        # Fetch all product IDs for the seller
        product_ids = await conn.fetch(
            "SELECT product_id FROM products WHERE seller_id = $1 ORDER BY created_at DESC",
            current_user.user_id
        )

        if not product_ids:
            return [] # Return empty list if no products found

        # Fetch details for each product ID using the helper function
        products_list = []
        for record in product_ids:
            product_id = record['product_id']
            product_details = await fetch_product_details(conn, product_id, current_user.user_id)
            if product_details:
                 products_list.append(product_details)

        return products_list

    except Exception as e:
        logger.error(f"Error getting seller products for user {current_user.user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        if conn:
            await pool.release(conn)

@router.get("/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: int,
    current_user: UserOut = Depends(get_current_user) # Allows any authenticated user to view a product
):
    """Get a specific product by ID"""
    pool = await get_pg_connection()
    conn = None
    try:
        conn = await pool.acquire()
        product = await fetch_product_details(conn, product_id)

        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )

        # Optional: Add visibility logic here if needed (e.g., hide 'pending' products from customers)
        # if product.status == 'pending' and current_user.role not in ['seller', 'admin']:
        #     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found") # Return 404 for invisibility

        return product

    except HTTPException:
        raise # Re-raise HTTPException if it was intentionally raised
    except Exception as e:
        logger.error(f"Error getting product {product_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        if conn:
            await pool.release(conn)

@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    product_update: ProductUpdate,
    current_user: UserOut = Depends(get_current_user)
):
    """Update a product (Seller who owns the product or Admin only)"""
    pool = await get_pg_connection()
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            # Check if product exists and get its seller_id and current type
            product_record = await conn.fetchrow(
                "SELECT seller_id, product_type FROM products WHERE product_id = $1",
                product_id
            )
            if not product_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )

            # Check if current user is the seller or an admin
            if product_record['seller_id'] != current_user.user_id and current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to update this product"
                )

            # Build update query dynamically based on provided fields
            update_fields = []
            params = []
            param_count = 1

            update_data = product_update.model_dump(exclude_unset=True)

            if "name" in update_data:
                update_fields.append(f"name = ${param_count}")
                params.append(update_data["name"])
                param_count += 1
            if "description" in update_data:
                update_fields.append(f"description = ${param_count}")
                params.append(update_data["description"])
                param_count += 1
            if "price" in update_data:
                update_fields.append(f"price = ${param_count}")
                params.append(update_data["price"])
                param_count += 1
            if "stock" in update_data:
                update_fields.append(f"stock = ${param_count}")
                params.append(update_data["stock"])
                param_count += 1
            if "category" in update_data:
                update_fields.append(f"category = ${param_count}")
                params.append(update_data["category"])
                param_count += 1
            if "status" in update_data:
                update_fields.append(f"status = ${param_count}")
                params.append(update_data["status"])
                param_count += 1
            if "product_type" in update_data: # Include product_type in update
                 update_fields.append(f"product_type = ${param_count}")
                 params.append(update_data["product_type"])
                 param_count += 1

            if not update_fields:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No fields to update"
                )

            # Add updated_at timestamp and product_id to parameters
            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(product_id)

            # Execute update
            update_query = f"""
                UPDATE products
                SET {', '.join(update_fields)}
                WHERE product_id = ${param_count}
            """
            await conn.execute(update_query, *params)

            # Fetch the updated product with images for the response
            updated_product = await fetch_product_details(conn, product_id)

            if not updated_product:
                 # Should not happen if update was successful, but as a safeguard
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch updated product details")

            return updated_product

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating product {product_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        if conn:
            await pool.release(conn)

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Delete a product (Seller who owns the product or Admin only)"""
    pool = await get_pg_connection()
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            # Check if product exists and get its seller_id
            product = await conn.fetchrow(
                "SELECT seller_id FROM products WHERE product_id = $1",
                product_id
            )
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )

            # Check if current user is the seller or an admin
            if product['seller_id'] != current_user.user_id and current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to delete this product"
                )

            # Delete related product images first
            await conn.execute(
                "DELETE FROM product_images WHERE product_id = $1",
                product_id
            )

            # Delete the product
            await conn.execute(
                "DELETE FROM products WHERE product_id = $1",
                product_id
            )

        return # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting product {product_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        if conn:
            await pool.release(conn)

@router.post("/{product_id}/upload-image", response_model=ProductOut)
async def upload_product_image(
    product_id: int,
    file: UploadFile = File(..., description="Image file to upload (max 5MB, JPEG/PNG)"),
    current_user: UserOut = Depends(get_current_user)
):
    """Upload an image for a product (Seller who owns the product or Admin only)"""
    pool = await get_pg_connection()
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            # Check if product exists and get its seller_id and product_type
            product_record = await conn.fetchrow(
                "SELECT seller_id, product_type FROM products WHERE product_id = $1",
                product_id
            )
            if not product_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )

            # Check if current user is the seller or an admin
            if product_record['seller_id'] != current_user.user_id and current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to upload images for this product"
                )

            # Check if the product is digital - digital products should not have physical images
            if product_record['product_type'] == 'digital':
                 raise HTTPException(
                     status_code=status.HTTP_400_BAD_REQUEST,
                     detail="Cannot upload images for digital products."
                 )

            # --- File Validation (Ensure it's sufficient) ---
            # Check file type and size (Example - adjust as needed)
            allowed_types = ["image/jpeg", "image/png"]
            max_size_mb = 5
            max_size_bytes = max_size_mb * 1024 * 1024

            if file.content_type not in allowed_types:
                 raise HTTPException(
                     status_code=status.HTTP_400_BAD_REQUEST,
                     detail=f"Invalid file type. Only {', '.join(allowed_types)} are allowed."
                 )

            # Check file size by reading chunks or seeking
            await file.seek(0, 2) # Seek to the end of the file
            total_size = file.tell() # Get the current position (file size)
            await file.seek(0) # Seek back to the beginning

            if total_size > max_size_bytes:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File size exceeds the maximum limit of {max_size_mb}MB."
                )

            # --- Upload to Cloudinary (Ensure error handling) ---
            try:
                upload_result = upload_image(file.file) # Pass the file stream
                logger.info(f"Cloudinary upload result: {upload_result}")

                image_url = upload_result.get("secure_url") or upload_result.get("url")
                if not image_url:
                     logger.error(f"Cloudinary upload result did not contain a URL: {upload_result}")
                     raise HTTPException(
                         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                         detail="Failed to get image URL from upload service."
                     )

            except Exception as e:
                logger.error(f"Cloudinary upload failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Image upload failed: {e}"
                )

            # --- Insert image URL into product_images table ---
            insert_image_query = """
                INSERT INTO product_images (product_id, image_url)
                VALUES ($1, $2)
                RETURNING image_id, product_id, image_url, uploaded_at
            """
            new_image_record = await conn.fetchrow(
                insert_image_query,
                product_id,
                image_url
            )

            # Fetch the updated product details including the new image
            updated_product = await fetch_product_details(conn, product_id)

            if not updated_product:
                 # Should not happen if insert was successful, but as a safeguard
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch product details after image upload")

            return updated_product

    except HTTPException:
        raise # Re-raise HTTPException if it was intentionally raised
    except Exception as e:
        logger.error(f"Error uploading image for product {product_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload image: {e}"
        )
    finally:
        if conn:
            await pool.release(conn)

@router.delete("/{product_id}/images/{image_id}")
async def delete_product_image(
    product_id: int,
    image_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Delete a product image (seller only)"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if product exists and belongs to seller
            product = await conn.fetchrow(
                "SELECT * FROM products WHERE product_id = $1",
                product_id
            )
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            # Only seller or admin can delete images
            if product["seller_id"] != current_user.user_id and current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to delete this image"
                )
            
            # Get image URL before deleting
            image = await conn.fetchrow(
                "SELECT image_url FROM product_images WHERE image_id = $1 AND product_id = $2",
                image_id, product_id
            )
            if not image:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Image not found"
                )
            
            # Delete from Cloudinary
            try:
                # Extract public_id from Cloudinary URL
                public_id = image["image_url"].split("/")[-1].split(".")[0]
                cloudinary.uploader.destroy(public_id)
            except Exception as e:
                print(f"Error deleting image from Cloudinary: {str(e)}")
            
            # Delete from database
            await conn.execute(
                "DELETE FROM product_images WHERE image_id = $1 AND product_id = $2",
                image_id, product_id
            )
            
            return {"message": "Image deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

class DeleteResponse(BaseModel):
    message: str

@router.delete("/{product_id}", response_model=DeleteResponse)
async def delete_product(
    product_id: int,
    current_user = Depends(require_role(["seller", "admin"]))
):
    """Delete a product (Seller/Admin only)"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
             async with conn.transaction():
                # Check if product exists and user is authorized
                existing_product = await conn.fetchrow(
                    "SELECT seller_id FROM products WHERE product_id = $1",
                    product_id
                )
                if not existing_product:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Product not found"
                    )

                # Authorize: Seller can only delete their own products
                if current_user['role'] == 'seller' and existing_product['seller_id'] != current_user['user_id']:
                     raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to delete this product"
                    )

                # Delete product (ON DELETE CASCADE will handle images)
                result = await conn.execute(
                    "DELETE FROM products WHERE product_id = $1",
                    product_id
                )

                if result != "DELETE 1":
                     raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to delete product"
                    )

                return DeleteResponse(message="Product deleted successfully")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

class ProductStatusUpdate(BaseModel):
    status: str

@router.put("/{product_id}/status", response_model=ProductOut)
async def update_product_status(
    product_id: int,
    status_update: ProductStatusUpdate,
    current_user: UserOut = Depends(get_current_user)
):
    """Update product status (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update product status"
        )
    
    # Validate status
    if status_update.status not in ["pending", "approved", "rejected"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status. Must be one of: pending, approved, rejected"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if product exists
            product = await conn.fetchrow(
                "SELECT * FROM products WHERE product_id = $1",
                product_id
            )
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            # Update product status
            updated_product = await conn.fetchrow(
                """
                UPDATE products 
                SET status = $1, updated_at = CURRENT_TIMESTAMP
                WHERE product_id = $2
                RETURNING *
                """,
                status_update.status, product_id
            )
            return dict(updated_product)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close() 