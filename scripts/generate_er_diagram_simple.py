#!/usr/bin/env python3
"""
Simple ER Diagram Generator using SQLAlchemy and graphviz
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.database import engine, Base
from sqlalchemy import inspect, MetaData
import subprocess

def generate_er_diagram():
    """Generate ER diagram."""
    print("=" * 80)
    print("Generating ER Diagram for PostgreSQL Database")
    print("=" * 80)
    print(f"\nDatabase: {settings.POSTGRES_DB}")
    print(f"Host: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}\n")
    
    try:
        # Try using eralchemy
        from eralchemy import render_er
        print("Using eralchemy to generate diagram...")
        output_file = "schema_er_diagram.png"
        render_er(settings.DATABASE_URL, output_file)
        print(f"\n✅ ER Diagram generated successfully!")
        print(f"📁 File: {output_file}")
        print(f"\nTo view:")
        print(f"  - Open {output_file} in your file explorer")
        print(f"  - Or run: xdg-open {output_file} (Linux/WSL)")
        return True
    except ImportError:
        print("❌ eralchemy not installed. Installing...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "eralchemy", "-q"])
            from eralchemy import render_er
            output_file = "schema_er_diagram.png"
            render_er(settings.DATABASE_URL, output_file)
            print(f"\n✅ ER Diagram generated successfully!")
            print(f"📁 File: {output_file}")
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            print("\nPlease install manually:")
            print("  pip install eralchemy")
            return False
    except Exception as e:
        error_msg = str(e).lower()
        print(f"❌ Error generating diagram: {e}")
        print("\nTroubleshooting:")
        
        if "graphviz" in error_msg or "pygraphviz" in error_msg:
            print("  Graphviz is required. Install it with:")
            print("    1. sudo apt-get install -y graphviz libgraphviz-dev pkg-config")
            print("    2. pip install graphviz")
            print("    3. Run this script again")
        else:
            print("  1. Make sure your database is running")
            print("  2. Check your database connection settings")
            print("  3. Ensure graphviz is installed:")
            print("     - sudo apt-get install -y graphviz libgraphviz-dev")
            print("     - pip install graphviz eralchemy")
        
        return False

if __name__ == "__main__":
    success = generate_er_diagram()
    sys.exit(0 if success else 1)

