from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from typing import List, Optional, Literal
from db.client import get_pg_connection
from models.product import ProductCreate, ProductOut, ProductUpdate, ProductImage
from routers.auth import get_current_user, require_role
from fastapi import Security
from config.cloudinary_config import upload_image, delete_image
import aiofiles
import os
import tempfile
import magic # for file type validation
import re

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

@router.post("/", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    product: ProductCreate,
    current_user = Depends(require_role(["seller", "admin"]))
):
    """Create a new product (Seller/Admin only)"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Determine initial status based on user role
                initial_status = "approved" if current_user['role'] == 'admin' else "pending"

                new_product = await conn.fetchrow(
                    """
                    INSERT INTO products (seller_id, name, description, price, stock, category, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING product_id, seller_id, name, description, price, stock, category, rating, created_at, status
                    """,
                    current_user['user_id'],
                    product.name,
                    product.description,
                    product.price,
                    product.stock,
                    product.category,
                    initial_status
                )

                if not new_product:
                     raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to create product"
                    )

                # Fetch the newly created product with images (should be empty initially)
                product_out = await fetch_product_with_images(conn, new_product['product_id'])
                return product_out
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.get("/", response_model=List[ProductOut])
async def read_products(
    search: Optional[str] = Query(None, description="Search product by name or description"),
    category: Optional[str] = Query(None, description="Filter by category"),
    min_price: Optional[float] = Query(None, description="Filter by minimum price", ge=0),
    max_price: Optional[float] = Query(None, description="Filter by maximum price", ge=0),
    min_rating: Optional[float] = Query(None, description="Filter by minimum rating", ge=0, le=5),
    max_rating: Optional[float] = Query(None, description="Filter by maximum rating", ge=0, le=5),
    sort_by: Optional[str] = Query("product_id", description="Field to sort by (e.g., price, rating, created_at, name)"),
    sort_order: Optional[str] = Query("asc", description="Sort order (asc or desc)"),
    page: int = Query(1, description="Page number", ge=1),
    limit: int = Query(10, description="Items per page", ge=1, le=100),
    current_user = Depends(get_current_user) # Inject current user
):
    """Get all products with optional search, filter, sorting, and pagination"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Base query
            query = "SELECT * FROM products"
            where_clauses = []
            query_params = []
            param_index = 1

            # Filter by status: only show approved products unless user is admin
            if current_user['role'] != 'admin':
                where_clauses.append(f"status = ${param_index}")
                query_params.append("approved")
                param_index += 1
            else:
                 # Optional: Admin can filter by status using query parameter if needed
                 # status_filter: Optional[Literal['pending', 'approved', 'rejected']] = Query(None)
                 # if status_filter:
                 #    where_clauses.append(f"status = ${param_index}")
                 #    query_params.append(status_filter)
                 #    param_index += 1
                 pass # Admin sees all statuses by default


            # Add search conditions
            if search:
                where_clauses.append(f"(name ILIKE ${param_index} OR description ILIKE ${param_index})")
                query_params.append(f"%{search}%")
                param_index += 1

            # Add filter conditions
            if category:
                where_clauses.append(f"category = ${param_index}")
                query_params.append(category)
                param_index += 1
            if min_price is not None:
                where_clauses.append(f"price >= ${param_index}")
                query_params.append(min_price)
                param_index += 1
            if max_price is not None:
                where_clauses.append(f"price <= ${param_index}")
                query_params.append(max_price)
                param_index += 1
            if min_rating is not None:
                where_clauses.append(f"rating >= ${param_index}")
                query_params.append(min_rating)
                param_index += 1
            if max_rating is not None:
                where_clauses.append(f"rating <= ${param_index}")
                query_params.append(max_rating)
                param_index += 1

            # Combine where clauses
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)

            # Add sorting
            valid_sort_fields = ["product_id", "name", "price", "stock", "rating", "created_at"]
            if sort_by and sort_by.lower() in valid_sort_fields:
                sort_order_upper = sort_order.upper() if sort_order else "ASC"
                query += f" ORDER BY {sort_by} {sort_order_upper}"
            else:
                # Default sorting if invalid field is provided
                 query += f" ORDER BY product_id ASC"


            # Add pagination
            offset = (page - 1) * limit
            query += f" LIMIT ${param_index} OFFSET ${param_index + 1}"
            query_params.append(limit)
            query_params.append(offset)
            param_index += 2 # Increment param_index for limit and offset


            products_data = await conn.fetch(query, *query_params)

            products_out = []
            for product in products_data:
                products_out.append(await fetch_product_with_images(conn, product['product_id']))

            # TODO: Add total count for pagination metadata if needed
            # count_query = "SELECT COUNT(*) FROM products"
            # if where_clauses:
            #     count_query += " WHERE " + " AND ".join(where_clauses)
            # total_count = await conn.fetchval(count_query, *query_params[:-2]) # Exclude limit and offset params
            # return {"total": total_count, "page": page, "limit": limit, "items": products_out}
            
            return products_out
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.get("/{product_id}", response_model=ProductOut)
async def read_product(product_id: int):
    """Get a specific product by ID"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            product = await fetch_product_with_images(conn, product_id)
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            return product
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
    current_user = Depends(require_role(["seller", "ADMIN"]))
):
    """Update a product (Seller/Admin only)"""
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

                # Authorize: Seller can only update their own products
                if current_user['role'] == 'seller' and existing_product['seller_id'] != current_user['user_id']:
                     raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to update this product"
                    )

                # Build update query dynamically
                update_fields = []
                update_values = []
                param_index = 1

                if product_update.name is not None:
                    update_fields.append(f"name = ${param_index}")
                    update_values.append(product_update.name)
                    param_index += 1
                if product_update.description is not None:
                    update_fields.append(f"description = ${param_index}")
                    update_values.append(product_update.description)
                    param_index += 1
                if product_update.price is not None:
                    update_fields.append(f"price = ${param_index}")
                    update_values.append(product_update.price)
                    param_index += 1
                if product_update.stock is not None:
                    update_fields.append(f"stock = ${param_index}")
                    update_values.append(product_update.stock)
                    param_index += 1
                if product_update.category is not None:
                    update_fields.append(f"category = ${param_index}")
                    update_values.append(product_update.category)
                    param_index += 1

                if not update_fields:
                    return await fetch_product_with_images(conn, product_id) # Nothing to update

                update_query = f"UPDATE products SET {', '.join(update_fields)} WHERE product_id = ${param_index} RETURNING *"
                update_values.append(product_id)

                updated_product = await conn.fetchrow(update_query, *update_values)

                if not updated_product:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to update product"
                    )

                product_out = await fetch_product_with_images(conn, updated_product['product_id'])
                return product_out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
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

                return # No content on successful deletion
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.put("/{product_id}/status", response_model=ProductOut)
async def update_product_status(
    product_id: int,
    new_status: Literal['pending', 'approved', 'rejected'] = Query(..., description="New product status"),
    current_user = Depends(require_role(["admin"]))
):
    """Update product status (Admin only)"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check if product exists
                existing_product = await conn.fetchrow(
                    "SELECT product_id FROM products WHERE product_id = $1",
                    product_id
                )
                if not existing_product:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Product not found"
                    )

                # Update the product status
                updated_product = await conn.fetchrow(
                    """
                    UPDATE products
                    SET status = $1
                    WHERE product_id = $2
                    RETURNING product_id, seller_id, name, description, price, stock, category, rating, created_at, status
                    """,
                    new_status,
                    product_id
                )

                if not updated_product:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to update product status"
                    )

                product_out = await fetch_product_with_images(conn, updated_product['product_id'])
                return product_out
    except HTTPException:
        raise
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
    current_user = Depends(require_role(["seller", "ADMIN"]))
):
    """Upload image for a product (Seller/Admin only)"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
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

            # Authorize: Seller can only upload images for their own products
            if current_user['role'] == 'seller' and existing_product['seller_id'] != current_user['user_id']:
                 raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to upload images for this product"
                )

            # File validation
            if not validate_filename(file.filename):
                 raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid filename"
                 )

            # Read file content asynchronously
            content = await file.read()
            
            if len(content) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File too large"
                )

            # Check file type using python-magic
            file_type = magic.from_buffer(content, mime=True)
            if file_type not in ALLOWED_IMAGE_TYPES:
                 raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid file type"
                 )

            # Save file temporarily for Cloudinary upload
            # Use tempfile for secure temporary file creation
            fd, path = tempfile.mkstemp(suffix=ALLOWED_IMAGE_TYPES[file_type])
            try:
                async with aiofiles.open(path, 'wb') as temp_file:
                    await temp_file.write(content)
                os.close(fd) # Close the file descriptor immediately after async write

                # Upload to Cloudinary
                upload_result = upload_image(path, folder="product_images") # Specify a folder
                if 'secure_url' not in upload_result:
                     raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to upload image to Cloudinary"
                    )
                
                image_url = upload_result['secure_url']

                # Save image URL to database
                await conn.execute(
                    "INSERT INTO product_images (product_id, image_url) VALUES ($1, $2)",
                    product_id, image_url
                )

                # Fetch the updated product with new image
                product_out = await fetch_product_with_images(conn, product_id)
                return product_out
            finally:
                # Clean up temporary file
                if os.path.exists(path):
                    os.remove(path)

    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred during image upload: {str(e)}"
        )
    finally:
        await pool.close() 