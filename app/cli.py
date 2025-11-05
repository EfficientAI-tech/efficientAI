"""CLI for EfficientAI platform."""

import click
import yaml
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional


@click.group()
def main():
    """EfficientAI - Voice AI Evaluation Platform CLI."""
    pass


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
def start(config: str, host: Optional[str], port: Optional[int], build_frontend: bool, reload: bool):
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
    
    # Start the server
    import uvicorn
    
    click.echo(f"🚀 Starting EfficientAI server...")
    click.echo(f"   Host: {settings.HOST}")
    click.echo(f"   Port: {settings.PORT}")
    click.echo(f"   API: http://{settings.HOST}:{settings.PORT}{settings.API_V1_PREFIX}")
    click.echo(f"   Frontend: http://{settings.HOST}:{settings.PORT}/")
    click.echo(f"   Docs: http://{settings.HOST}:{settings.PORT}/docs")
    
    # Use import string for reload to work properly
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=reload,
    )


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

