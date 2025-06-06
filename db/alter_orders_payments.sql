-- Add missing columns to the orders table
-- tracking_number and estimated_delivery were intended for the orders table
ALTER TABLE orders ADD COLUMN IF NOT EXISTS tracking_number VARCHAR(100);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS estimated_delivery TIMESTAMP WITH TIME ZONE;

-- Make shipping_address nullable in orders table for digital products
ALTER TABLE orders ALTER COLUMN shipping_address DROP NOT NULL;

-- Adjust the payments table foreign key
-- Payments should typically be linked to the entire order, not just an order item.
-- Drop the old foreign key referencing order_items (previously purchase_history)
-- Note: You might need to replace 'payments_purchase_id_fkey' with the actual name of the foreign key constraint if it's different.
-- You can find the constraint name by looking at your table definition in a database tool.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE constraint_schema = 'public'
        AND table_name = 'payments'
        AND constraint_name = 'payments_purchase_id_fkey' -- Replace if constraint name is different
    ) THEN
        ALTER TABLE payments DROP CONSTRAINT payments_purchase_id_fkey;
    END IF;
END
$$;

-- Add a new column order_id to the payments table if it doesn't exist
ALTER TABLE payments ADD COLUMN IF NOT EXISTS order_id INTEGER;

-- Add a new foreign key constraint referencing the orders table
ALTER TABLE payments ADD CONSTRAINT payments_order_id_fkey FOREIGN KEY (order_id) REFERENCES orders(order_id);

-- You might need to migrate existing data in the payments table
-- If you have existing payment records linked via purchase_id (from the old structure),
-- you would need to populate the new order_id column based on the relationship
-- between order_items (where the old purchase_id is the PK) and orders (via order_id in order_items).
-- This is a complex data migration step and depends on your existing data relationships.
-- Example (conceptual, requires careful adaptation):
/*
UPDATE payments p
SET order_id = oi.order_id
FROM order_items oi
WHERE p.purchase_id = oi.purchase_id;

-- After migrating data, you might consider dropping the old purchase_id column from payments
-- ALTER TABLE payments DROP COLUMN purchase_id;
*/

-- Note: The primary key column in order_items is still named 'purchase_id'.
-- While the code handles this with an alias ('order_item_id'), it might be cleaner
-- to rename this column in the database as well if desired:
-- ALTER TABLE order_items RENAME COLUMN purchase_id TO order_item_id; 