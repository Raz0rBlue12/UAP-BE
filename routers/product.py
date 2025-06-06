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

@router.post("", response_model=ProductOut)
async def create_product(
    product: ProductCreate,
    current_user: UserOut = Depends(require_role(["seller", "admin"]))
):
    """Create a new product (seller only)"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Determine initial status based on user role
            initial_status = "approved" if current_user.role == "admin" else "pending"
            
            # Create product
            new_product = await conn.fetchrow(
                """
                INSERT INTO products (
                    seller_id, name, description, price, stock, category, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
                """,
                current_user.user_id, product.name, product.description,
                product.price, product.stock, product.category, initial_status
            )
            return dict(new_product)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

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
    current_user: UserOut = Depends(get_current_user)
):
    """Get all products for the current seller"""
    if current_user.role != "seller" and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only sellers can view their products"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            products = await conn.fetch(
                """
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
                WHERE p.seller_id = $1
                GROUP BY p.product_id
                ORDER BY p.created_at DESC
                """,
                current_user.user_id
            )
            
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

@router.get("/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: int,
    current_user: Optional[UserOut] = Depends(get_current_user)
):
    """Get a specific product by ID"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            product = await conn.fetchrow(
                """
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
                WHERE p.product_id = $1
                GROUP BY p.product_id
                """,
                product_id
            )
            
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            # Convert record to dictionary and parse images
            product_dict = dict(product)
            if isinstance(product_dict['images'], str):
                import json
                product_dict['images'] = json.loads(product_dict['images'])
            
            return product_dict
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Delete a product (seller only)"""
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
            
            # Only seller or admin can delete their products
            if product["seller_id"] != current_user.user_id and current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to delete this product"
                )
            
            # Delete product images from Cloudinary first
            images = await conn.fetch(
                "SELECT image_url FROM product_images WHERE product_id = $1",
                product_id
            )
            
            for image in images:
                try:
                    # Extract public_id from Cloudinary URL
                    public_id = image["image_url"].split("/")[-1].split(".")[0]
                    cloudinary.uploader.destroy(public_id)
                except Exception as e:
                    print(f"Error deleting image from Cloudinary: {str(e)}")
            
            # Delete product (cascade will handle product_images)
            await conn.execute(
                "DELETE FROM products WHERE product_id = $1",
                product_id
            )
            
            return {"message": "Product deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    product_update: ProductUpdate,
    current_user: UserOut = Depends(get_current_user)
):
    """Update a product (seller only)"""
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
            
            # Only seller or admin can update their products
            if product["seller_id"] != current_user.user_id and current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to update this product"
                )
            
            # Build update query dynamically based on provided fields
            update_fields = []
            values = []
            param_count = 1
            
            if product_update.name is not None:
                update_fields.append(f"name = ${param_count}")
                values.append(product_update.name)
                param_count += 1
            
            if product_update.description is not None:
                update_fields.append(f"description = ${param_count}")
                values.append(product_update.description)
                param_count += 1
            
            if product_update.price is not None:
                update_fields.append(f"price = ${param_count}")
                values.append(product_update.price)
                param_count += 1
            
            if product_update.stock is not None:
                update_fields.append(f"stock = ${param_count}")
                values.append(product_update.stock)
                param_count += 1
            
            if product_update.category is not None:
                update_fields.append(f"category = ${param_count}")
                values.append(product_update.category)
                param_count += 1
            
            if not update_fields:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No fields to update"
                )
            
            # Add updated_at timestamp
            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            
            # Add product_id to values
            values.append(product_id)
            
            # Execute update
            query = f"""
                UPDATE products 
                SET {', '.join(update_fields)}
                WHERE product_id = ${param_count}
                RETURNING *
            """
            
            updated_product = await conn.fetchrow(query, *values)
            
            # Fetch the updated product with its images
            product_data = await conn.fetchrow(
                """
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
                WHERE p.product_id = $1
                GROUP BY p.product_id
                """,
                product_id
            )
            
            # Convert the record to a dictionary
            product_dict = dict(product_data)
            
            # Parse the images JSON string into a list
            if isinstance(product_dict['images'], str):
                import json
                product_dict['images'] = json.loads(product_dict['images'])
            
            return product_dict
            
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

@router.post("/{product_id}/upload-image", response_model=ProductOut)
async def upload_product_image(
    product_id: int,
    file: UploadFile = File(...),
    current_user: UserOut = Depends(get_current_user)
):
    """Upload an image for a product (seller only)"""
    # Validate file type
    if not file.content_type.startswith('image/'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image"
        )
    
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
            
            # Only seller or admin can upload images
            if product["seller_id"] != current_user.user_id and current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to upload images for this product"
                )
            
            # Upload image to Cloudinary
            try:
                # Read file content
                contents = await file.read()
                
                # Upload to Cloudinary
                upload_result = cloudinary.uploader.upload(
                    contents,
                    folder="product_images",
                    resource_type="image"
                )
                
                # Get the secure URL
                image_url = upload_result.get("secure_url") or upload_result.get("url")
                if not image_url:
                    raise Exception("No image URL in upload result")
                
                # Add image URL to product_images table
                await conn.execute(
                    """
                    INSERT INTO product_images (product_id, image_url)
                    VALUES ($1, $2)
                    """,
                    product_id, image_url
                )
                
                # Fetch the updated product with its images
                product_data = await conn.fetchrow(
                    """
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
                    WHERE p.product_id = $1
                    GROUP BY p.product_id
                    """,
                    product_id
                )
                
                # Convert the record to a dictionary
                product_dict = dict(product_data)
                
                # Parse the images JSON string into a list
                if isinstance(product_dict['images'], str):
                    import json
                    product_dict['images'] = json.loads(product_dict['images'])
                
                return product_dict
                
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"An error occurred during image upload: {str(e)}"
                )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

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