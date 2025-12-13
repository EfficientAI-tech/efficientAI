-- Quick fix: Make phone_number nullable in agents table
-- This fixes the IntegrityError when creating agents with WEB_CALL medium
-- Run this with: psql -U efficientai -d efficientai -f fix_phone_number.sql
-- Or connect to your database and run the ALTER TABLE command below

-- Check current state
SELECT 
    column_name, 
    is_nullable 
FROM information_schema.columns 
WHERE table_name = 'agents' 
AND column_name = 'phone_number';

-- Make phone_number nullable
ALTER TABLE agents ALTER COLUMN phone_number DROP NOT NULL;

-- Verify the change
SELECT 
    column_name, 
    is_nullable 
FROM information_schema.columns 
WHERE table_name = 'agents' 
AND column_name = 'phone_number';

