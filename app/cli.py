"""CLI for EfficientAI platform."""

import click
import yaml
import os
import sys
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional


@click.group()
def main():
    """EfficientAI - Voice AI Evaluation Platform CLI."""
    pass


class FrontendWatcher:
    """Watch frontend files and rebuild on changes."""
    
    def __init__(self, frontend_dir: Path):
        self.frontend_dir = frontend_dir
        self.watching = False
        self.thread = None
        self.last_build_time = 0
        self.build_lock = threading.Lock()
        
    def should_rebuild(self) -> bool:
        """Check if frontend files have changed."""
        src_dir = self.frontend_dir / "src"
        if not src_dir.exists():
            return False
        
        # Check modification time of source files
        max_mtime = 0
        for ext in [".tsx", ".ts", ".css", ".jsx", ".js"]:
            for file_path in src_dir.rglob(f"*{ext}"):
                if file_path.is_file():
                    max_mtime = max(max_mtime, file_path.stat().st_mtime)
        
        # Also check config files
        config_files = [
            self.frontend_dir / "vite.config.ts",
            self.frontend_dir / "tailwind.config.js",
            self.frontend_dir / "tsconfig.json",
            self.frontend_dir / "package.json",
        ]
        for config_file in config_files:
            if config_file.exists():
                max_mtime = max(max_mtime, config_file.stat().st_mtime)
        
        if max_mtime > self.last_build_time:
            self.last_build_time = max_mtime
            return True
        return False
    
    def build_frontend(self):
        """Rebuild the frontend."""
        with self.build_lock:
            try:
                click.echo("\n🔄 Frontend files changed, rebuilding...")
                result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=self.frontend_dir,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    click.echo("✅ Frontend rebuilt successfully")
                else:
                    click.echo(f"⚠️  Frontend build had warnings (check logs)", err=True)
                    if result.stderr:
                        click.echo(result.stderr[:500], err=True)  # Show first 500 chars
            except Exception as e:
                click.echo(f"❌ Frontend build error: {e}", err=True)
    
    def watch_loop(self):
        """Watch loop that runs in background thread."""
        while self.watching:
            try:
                if self.should_rebuild():
                    self.build_frontend()
                time.sleep(1)  # Check every second
            except Exception as e:
                click.echo(f"❌ Watcher error: {e}", err=True)
                time.sleep(5)  # Wait longer on error
    
    def start(self):
        """Start the watcher in a background thread."""
        if self.watching:
            return
        self.watching = True
        # Set initial build time to avoid rebuilding immediately
        self.last_build_time = time.time()
        self.thread = threading.Thread(target=self.watch_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Stop the watcher."""
        self.watching = False
        if self.thread:
            self.thread.join(timeout=1)


def start_frontend_watcher(frontend_dir: Path) -> FrontendWatcher:
    """Start a frontend file watcher."""
    watcher = FrontendWatcher(frontend_dir)
    watcher.start()
    return watcher


@main.command()
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed migration output",
)
def migrate(verbose: bool):
    """Run pending database migrations."""
    import logging
    from app.core.migrations import run_migrations, ensure_migrations_directory
    
    if verbose:
        logging.basicConfig(level=logging.INFO)
    
    click.echo("🔄 Running database migrations...")
    ensure_migrations_directory()
    
    try:
        run_migrations()
        click.echo("✅ All migrations completed successfully!")
    except Exception as e:
        click.echo(f"❌ Migration failed: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, readable=True),
    default="config.yml",
    help="Path to configuration YAML file",
)
@click.option(
    "--host",
    default=None,
    help="Host to bind to (overrides config)",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Port to bind to (overrides config)",
)
@click.option(
    "--build-frontend/--no-build-frontend",
    default=True,
    help="Build frontend before starting (default: True)",
)
@click.option(
    "--reload/--no-reload",
    default=True,
    help="Enable auto-reload for development (default: True)",
)
@click.option(
    "--watch-frontend/--no-watch-frontend",
    default=False,
    help="Watch frontend files and rebuild automatically (default: False)",
)
def start(config: str, host: Optional[str], port: Optional[int], build_frontend: bool, reload: bool, watch_frontend: bool):
    """Start the EfficientAI application server."""
    from app.config import load_config_from_file, settings
    
    # Load configuration from YAML file
    config_path = Path(config)
    if not config_path.exists():
        click.echo(f"❌ Config file not found: {config}", err=True)
        click.echo(f"💡 Create a config.yml file or use --config to specify a different path.", err=True)
        sys.exit(1)
    
    try:
        load_config_from_file(str(config_path))
        click.echo(f"✅ Loaded configuration from {config_path}")
    except Exception as e:
        click.echo(f"❌ Error loading config: {e}", err=True)
        sys.exit(1)
    
    # Override with CLI options if provided
    if host:
        settings.HOST = host
    if port:
        settings.PORT = port
    
    # Build frontend if requested
    # Check if frontend is already built
    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
    if build_frontend and frontend_dist.exists() and any(frontend_dist.iterdir()):
        if not click.confirm("Frontend dist directory already exists. Rebuild anyway?"):
            build_frontend = False
    
    if build_frontend:
        click.echo("🔨 Building frontend...")
        frontend_dir = Path(__file__).parent.parent / "frontend"
        if not frontend_dir.exists():
            click.echo(f"❌ Frontend directory not found: {frontend_dir}", err=True)
            sys.exit(1)
        
        try:
            # Check if node_modules exists, if not, install dependencies
            if not (frontend_dir / "node_modules").exists():
                click.echo("📦 Installing frontend dependencies...")
                subprocess.run(
                    ["npm", "install"],
                    cwd=frontend_dir,
                    check=True,
                    capture_output=True,
                )
            
            # Build frontend (show output in real-time for better debugging)
            click.echo("   Running TypeScript check and Vite build...")
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=frontend_dir,
                check=False,  # Don't fail immediately, we'll check return code
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                click.echo(f"❌ Frontend build failed with return code {result.returncode}", err=True)
                if result.stdout:
                    click.echo(f"\nSTDOUT:\n{result.stdout}", err=True)
                if result.stderr:
                    click.echo(f"\nSTDERR:\n{result.stderr}", err=True)
                click.echo("\n💡 Try running 'npm run build' manually in the frontend directory to see full error details.", err=True)
                sys.exit(1)
            
            click.echo("✅ Frontend built successfully")
        except subprocess.CalledProcessError as e:
            click.echo(f"❌ Error building frontend:", err=True)
            if e.stdout:
                click.echo(f"STDOUT:\n{e.stdout}", err=True)
            if e.stderr:
                click.echo(f"STDERR:\n{e.stderr}", err=True)
            click.echo(f"\nReturn code: {e.returncode}", err=True)
            sys.exit(1)
        except FileNotFoundError:
            click.echo("❌ npm not found. Please install Node.js and npm.", err=True)
            sys.exit(1)
    
    # Start frontend watcher if requested
    frontend_watcher = None
    if watch_frontend:
        click.echo("👀 Starting frontend file watcher...")
        frontend_dir = Path(__file__).parent.parent / "frontend"
        frontend_watcher = start_frontend_watcher(frontend_dir)
    
    # Start the server
    import uvicorn
    
    click.echo(f"🚀 Starting EfficientAI server...")
    click.echo(f"   Host: {settings.HOST}")
    click.echo(f"   Port: {settings.PORT}")
    click.echo(f"   API: http://{settings.HOST}:{settings.PORT}{settings.API_V1_PREFIX}")
    click.echo(f"   Frontend: http://{settings.HOST}:{settings.PORT}/")
    click.echo(f"   Docs: http://{settings.HOST}:{settings.PORT}/docs")
    if watch_frontend:
        click.echo(f"   Frontend watcher: Active (rebuilding on file changes)")
    
    # Use import string for reload to work properly
    try:
        uvicorn.run(
            "app.main:app",
            host=settings.HOST,
            port=settings.PORT,
            reload=reload,
        )
    finally:
        # Clean up watcher on exit
        if frontend_watcher:
            frontend_watcher.stop()


@main.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="config.yml",
    help="Output file path for example config",
)
def init_config(output: str):
    """Generate an example configuration file."""
    example_config = """# EfficientAI Configuration File

# Application Settings
app:
  name: "Voice AI Evaluation Platform"
  version: "0.1.0"
  debug: true
  secret_key: "your-secret-key-here-change-in-production"

# Server Settings
server:
  host: "0.0.0.0"
  port: 8000

# Database Configuration
database:
  url: "postgresql://efficientai:password@localhost:5432/efficientai"
  # Alternative: specify individual components
  # user: "efficientai"
  # password: "password"
  # host: "localhost"
  # port: 5432
  # db: "efficientai"

# Redis Configuration
redis:
  url: "redis://localhost:6379/0"
  # Alternative: specify individual components
  # host: "localhost"
  # port: 6379
  # db: 0

# Celery Configuration
celery:
  broker_url: "redis://localhost:6379/0"
  result_backend: "redis://localhost:6379/0"

# File Storage
storage:
  upload_dir: "./uploads"
  max_file_size_mb: 500
  allowed_audio_formats:
    - "wav"
    - "mp3"
    - "flac"
    - "m4a"

# CORS Settings
cors:
  origins:
    - "http://localhost:3000"
    - "http://localhost:8000"

# API Settings
api:
  prefix: "/api/v1"
  key_header: "X-API-Key"
  rate_limit_per_minute: 60
"""
    
    output_path = Path(output)
    if output_path.exists():
        if not click.confirm(f"File {output} already exists. Overwrite?"):
            click.echo("Cancelled.")
            return
    
    try:
        output_path.write_text(example_config)
        click.echo(f"✅ Created example configuration file: {output}")
        click.echo(f"💡 Edit {output} with your settings, then run: eai start --config {output}")
    except Exception as e:
        click.echo(f"❌ Error creating config file: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

