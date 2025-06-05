-- Drop existing constraint
ALTER TABLE users DROP CONSTRAINT users_role_check;

-- Add new constraint with 'ADMIN' role
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('customer', 'seller', 'ADMIN'));

-- Create first admin user (password: Admin@123456)
INSERT INTO users (username, email, password_hash, role)
VALUES (
    'admin',
    'admin@example.com',
    '$2b$12$cwfLYzeF4vHDl6rSobavK.txWwYxOUOuB7jSzH8xnRvHENhrYDnfi',
    'ADMIN'
) ON CONFLICT (email) DO NOTHING;

-- Create admin profile
INSERT INTO user_profiles (user_id, full_name, bio)
SELECT user_id, 'System Administrator', 'Main System Administrator'
FROM users
WHERE email = 'admin@example.com'
ON CONFLICT (user_id) DO NOTHING; 