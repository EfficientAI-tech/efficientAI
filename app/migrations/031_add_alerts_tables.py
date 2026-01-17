"""
Migration 031: Add alerts and alert_history tables

This migration creates the tables needed for the alerting feature:
- alerts: Stores alert configurations
- alert_history: Stores triggered alert events
"""

from sqlalchemy import text

description = "Add alerts and alert_history tables for the alerting feature"


def upgrade(db):
    """Run the migration."""
    # Check if alerts table already exists
    result = db.execute(text("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_name = 'alerts'
    """))
    
    if not result.fetchone():
        # Create alerts table
        db.execute(text("""
            CREATE TABLE alerts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                name VARCHAR(255) NOT NULL,
                description TEXT,
                
                -- Metric condition configuration
                metric_type VARCHAR(50) NOT NULL DEFAULT 'number_of_calls',
                aggregation VARCHAR(20) NOT NULL DEFAULT 'sum',
                operator VARCHAR(10) NOT NULL DEFAULT '>',
                threshold_value FLOAT NOT NULL,
                time_window_minutes INTEGER NOT NULL DEFAULT 60,
                
                -- Agent selection (JSON array of agent UUIDs, null means all agents)
                agent_ids JSONB,
                
                -- Notification configuration
                notify_frequency VARCHAR(20) NOT NULL DEFAULT 'immediate',
                notify_emails JSONB,
                notify_webhooks JSONB,
                
                -- Status
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                
                -- Metadata
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                created_by VARCHAR(255)
            )
        """))
        
        # Create indexes for alerts table
        db.execute(text("""
            CREATE INDEX idx_alerts_organization_id ON alerts(organization_id)
        """))
        db.execute(text("""
            CREATE INDEX idx_alerts_status ON alerts(status)
        """))
        
        print("Created alerts table with indexes")
    else:
        print("alerts table already exists")
    
    # Check if alert_history table already exists
    result = db.execute(text("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_name = 'alert_history'
    """))
    
    if not result.fetchone():
        # Create alert_history table
        db.execute(text("""
            CREATE TABLE alert_history (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                alert_id UUID NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
                
                -- Trigger information
                triggered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
                triggered_value FLOAT NOT NULL,
                threshold_value FLOAT NOT NULL,
                
                -- Status tracking
                status VARCHAR(20) NOT NULL DEFAULT 'triggered',
                
                -- Notification tracking
                notified_at TIMESTAMP WITH TIME ZONE,
                notification_details JSONB,
                
                -- Resolution
                acknowledged_at TIMESTAMP WITH TIME ZONE,
                acknowledged_by VARCHAR(255),
                resolved_at TIMESTAMP WITH TIME ZONE,
                resolved_by VARCHAR(255),
                resolution_notes TEXT,
                
                -- Additional context
                context_data JSONB,
                
                -- Metadata
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        
        # Create indexes for alert_history table
        db.execute(text("""
            CREATE INDEX idx_alert_history_organization_id ON alert_history(organization_id)
        """))
        db.execute(text("""
            CREATE INDEX idx_alert_history_alert_id ON alert_history(alert_id)
        """))
        db.execute(text("""
            CREATE INDEX idx_alert_history_status ON alert_history(status)
        """))
        db.execute(text("""
            CREATE INDEX idx_alert_history_triggered_at ON alert_history(triggered_at)
        """))
        
        print("Created alert_history table with indexes")
    else:
        print("alert_history table already exists")
    
    db.commit()


def downgrade(db):
    """Rollback the migration."""
    # Drop alert_history table first (due to foreign key)
    db.execute(text("DROP TABLE IF EXISTS alert_history CASCADE"))
    
    # Drop alerts table
    db.execute(text("DROP TABLE IF EXISTS alerts CASCADE"))
    
    db.commit()
    print("Dropped alerts and alert_history tables")
