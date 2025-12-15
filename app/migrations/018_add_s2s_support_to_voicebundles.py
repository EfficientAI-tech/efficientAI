"""
Migration: Add S2S (Speech-to-Speech) support to VoiceBundles
"""

description = "Add bundle_type and S2S fields to voicebundles table, make STT/LLM/TTS fields nullable"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    
    # Add bundle_type column with default value (as VARCHAR, SQLAlchemy handles enum conversion)
    db.execute(text("""
        ALTER TABLE voicebundles 
        ADD COLUMN IF NOT EXISTS bundle_type VARCHAR(50) DEFAULT 'stt_llm_tts' NOT NULL
    """))
    
    # Make STT fields nullable
    db.execute(text("""
        ALTER TABLE voicebundles 
        ALTER COLUMN stt_provider DROP NOT NULL,
        ALTER COLUMN stt_model DROP NOT NULL
    """))
    
    # Make LLM fields nullable
    db.execute(text("""
        ALTER TABLE voicebundles 
        ALTER COLUMN llm_provider DROP NOT NULL,
        ALTER COLUMN llm_model DROP NOT NULL
    """))
    
    # Make TTS fields nullable
    db.execute(text("""
        ALTER TABLE voicebundles 
        ALTER COLUMN tts_provider DROP NOT NULL,
        ALTER COLUMN tts_model DROP NOT NULL
    """))
    
    # Add S2S fields
    db.execute(text("""
        ALTER TABLE voicebundles 
        ADD COLUMN IF NOT EXISTS s2s_provider modelprovider,
        ADD COLUMN IF NOT EXISTS s2s_model VARCHAR(255),
        ADD COLUMN IF NOT EXISTS s2s_config JSONB
    """))
    
    db.commit()

