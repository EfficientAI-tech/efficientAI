"""
Migration 028: Normalize provider values to lowercase in voicebundles table

This migration converts the provider columns from enum type to VARCHAR
and normalizes values to lowercase to match the ModelProvider enum values.
"""

from sqlalchemy import text

description = "Convert provider columns to VARCHAR and normalize to lowercase in voicebundles table"


def upgrade(db):
    """Convert provider columns to VARCHAR and normalize to lowercase."""
    
    # First, check if columns are enum type and convert to VARCHAR if needed
    # Then normalize the values to lowercase
    
    provider_columns = ['stt_provider', 'llm_provider', 'tts_provider', 's2s_provider']
    
    for column in provider_columns:
        # Check column data type
        result = db.execute(text(f"""
            SELECT data_type, udt_name 
            FROM information_schema.columns 
            WHERE table_name = 'voicebundles' 
            AND column_name = '{column}'
        """))
        row = result.fetchone()
        
        if row:
            data_type, udt_name = row
            
            # If it's an enum (USER-DEFINED), convert to VARCHAR
            if data_type == 'USER-DEFINED' or udt_name == 'modelprovider':
                print(f"Converting {column} from enum to VARCHAR...")
                db.execute(text(f"""
                    ALTER TABLE voicebundles 
                    ALTER COLUMN {column} TYPE VARCHAR(50) 
                    USING {column}::text
                """))
            
            # Now normalize to lowercase (it's now VARCHAR)
            db.execute(text(f"""
                UPDATE voicebundles 
                SET {column} = LOWER({column}::text) 
                WHERE {column} IS NOT NULL
            """))
    
    print("Normalized provider values in voicebundles table")
    db.commit()


def downgrade(db):
    """This migration is not reversible - values remain lowercase and as VARCHAR."""
    print("Note: Provider columns will remain as VARCHAR with lowercase values (no downgrade action)")
    pass
