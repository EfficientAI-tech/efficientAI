-- Quick fix: Add name column to manual_transcriptions table
-- Run this SQL directly in your PostgreSQL database if migration hasn't run yet

ALTER TABLE manual_transcriptions 
ADD COLUMN IF NOT EXISTS name VARCHAR(255);

-- Note: PostgreSQL doesn't support IF NOT EXISTS for ALTER TABLE ADD COLUMN
-- If the column already exists, you'll get an error - that's okay, just ignore it
-- Or use this safer version:

DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'manual_transcriptions' 
        AND column_name = 'name'
    ) THEN
        ALTER TABLE manual_transcriptions ADD COLUMN name VARCHAR(255);
    END IF;
END $$;

