-- Create the new orders table
CREATE TABLE IF NOT EXISTS orders (
    order_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    shipping_address TEXT, -- Made nullable for digital products
    payment_method VARCHAR(50) NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL CHECK (total_amount >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tracking_number VARCHAR(100),
    estimated_delivery TIMESTAMP WITH TIME ZONE
);

-- Rename the existing purchase_history table to order_items
-- This assumes purchase_history currently stores individual product items.
ALTER TABLE purchase_history RENAME TO order_items;

-- Add order_id foreign key to the order_items table
ALTER TABLE order_items ADD COLUMN order_id INTEGER REFERENCES orders(order_id);

-- Drop the redundant user_id column from order_items
-- This is now stored in the orders table
-- Ensure no other constraints/indices depend on user_id in order_items before dropping
ALTER TABLE order_items DROP COLUMN user_id;

-- Drop the redundant purchase_date column from order_items
-- This is now stored in the orders table (as created_at)
ALTER TABLE order_items DROP COLUMN purchase_date;

-- You might need to update existing data here
-- For example, if you had data in purchase_history before running this script,
-- you would need to create corresponding entries in the new 'orders' table
-- and link the old 'purchase_history' (now 'order_items') entries to them
-- by populating the new order_id column. This is a manual data migration step.
-- This part is complex and depends on your existing data, so it's omitted here.

-- Add trigger to update updated_at timestamp on the orders table
-- (Assuming update_updated_at_column function already exists from previous steps)
-- If the function does NOT exist, you'll need to create it:
/*
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';
*/
CREATE TRIGGER update_orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column(); 