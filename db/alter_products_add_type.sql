-- Add product_type column to the products table
-- This column will distinguish between physical and digital products.
ALTER TABLE products ADD COLUMN IF NOT EXISTS product_type VARCHAR(20) NOT NULL DEFAULT 'physical' CHECK (product_type IN ('physical', 'digital'));

-- Note: If you have existing data, the new column will be populated with the default value 'physical'.
-- If you have existing digital products, you will need to manually update their product_type to 'digital' after running this script.
-- Example UPDATE statement (run this manually if needed):
-- UPDATE products SET product_type = 'digital' WHERE product_id IN (list_of_your_digital_product_ids); 