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
@click.option(
    "--force-rebuild",
    is_flag=True,
    default=False,
    help="Force rebuild of frontend without prompting",
)
@click.option(
    "--skip-migrations",
    is_flag=True,
    default=False,
    help="Skip running migrations before starting (not recommended)",
)
def start(config: str, host: Optional[str], port: Optional[int], build_frontend: bool, reload: bool, watch_frontend: bool, force_rebuild: bool, skip_migrations: bool):
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
        # If watching, we always want to rebuild to catch latest changes at start
        if not force_rebuild and not watch_frontend and not click.confirm("Frontend dist directory already exists. Rebuild anyway?"):
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
                    ["npm", "install", "--legacy-peer-deps"],
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
    
    # Initialize DB tables and run migrations before starting (unless explicitly skipped)
    if not skip_migrations:
        click.echo("🔄 Initializing database and running migrations...")
        from app.database import init_db
        from app.core.migrations import run_migrations, ensure_migrations_directory
        try:
            init_db()
            ensure_migrations_directory()
            run_migrations()
            click.echo("✅ Database initialized and migrations completed")
        except Exception as e:
            click.echo(f"❌ Migration failed: {e}", err=True)
            click.echo("💡 You can skip migrations with --skip-migrations (not recommended)", err=True)
            sys.exit(1)
    else:
        click.echo("⚠️  Skipping migrations (not recommended - migrations will run on startup)")
    
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
    "--config",
    "-c",
    type=click.Path(exists=True, readable=True),
    default="config.yml",
    help="Path to configuration YAML file",
)
@click.option(
    "--loglevel",
    "-l",
    default="info",
    type=click.Choice(["debug", "info", "warning", "error", "critical"], case_sensitive=False),
    help="Log level for Celery worker",
)
@click.option(
    "--queues",
    "-Q",
    "queues",
    default=None,
    help=(
        "Comma-separated list of Celery queues this worker should consume "
        "(forwarded to celery's -Q flag). Defaults to the default queue."
    ),
)
@click.option(
    "--concurrency",
    default=None,
    type=int,
    help="Number of concurrent worker processes/threads (Celery --concurrency).",
)
@click.option(
    "--pool",
    "-P",
    "pool",
    default=None,
    type=click.Choice(["prefork", "threads", "solo", "eventlet", "gevent"], case_sensitive=False),
    help="Celery worker pool implementation (forwarded to celery's -P flag).",
)
def worker(config: str, loglevel: str, queues: Optional[str], concurrency: Optional[int], pool: Optional[str]):
    """Start the Celery worker for background task processing."""
    from app.config import load_config_from_file
    
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
    
    click.echo(f"🚀 Starting Celery worker...")
    click.echo(f"   Log level: {loglevel}")
    if queues:
        click.echo(f"   Queues: {queues}")
    if concurrency is not None:
        click.echo(f"   Concurrency: {concurrency}")
    if pool:
        click.echo(f"   Pool: {pool}")
    
    # Start Celery worker
    try:
        import subprocess
        cmd = ["celery", "-A", "app.workers.celery_app", "worker", f"--loglevel={loglevel}"]
        if queues:
            cmd.append(f"--queues={queues}")
        if concurrency is not None:
            cmd.append(f"--concurrency={concurrency}")
        if pool:
            cmd.append(f"--pool={pool}")
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        click.echo("\n👋 Celery worker stopped")
    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Celery worker failed: {e}", err=True)
        sys.exit(1)
    except FileNotFoundError:
        click.echo("❌ Celery not found. Please install it: pip install celery", err=True)
        sys.exit(1)


@main.command("telephony-worker")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, readable=True),
    default="config.yml",
    help="Path to configuration YAML file",
)
@click.option("--host", default=None, help="Host to bind (default from config)")
@click.option("--port", default=None, type=int, help="Media server port (default 8001)")
def telephony_worker(config: str, host: Optional[str], port: Optional[int]):
    """Start the media server for live voice WebSocket connections."""
    from app.config import load_config_from_file, settings

    config_path = Path(config)
    if not config_path.exists():
        click.echo(f"❌ Config file not found: {config}", err=True)
        sys.exit(1)

    try:
        load_config_from_file(str(config_path))
    except Exception as e:
        click.echo(f"❌ Error loading config: {e}", err=True)
        sys.exit(1)

    os.environ["SERVICE_MODE"] = "media"
    bind_host = host or settings.HOST
    bind_port = port or settings.MEDIA_PORT

    import uvicorn

    click.echo(f"🎙️  Starting EfficientAI media server on {bind_host}:{bind_port}")
    uvicorn.run(
        "app.media_main:app",
        host=bind_host,
        port=bind_port,
        reload=False,
    )


@main.command("start-worker-all")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, readable=True),
    default="config.yml",
    help="Path to configuration YAML file",
)
@click.option("--loglevel", "-l", default="info", help="Celery log level")
@click.option("--media-port", default=None, type=int, help="Media server port (default 8001)")
def start_worker_all(config: str, loglevel: str, media_port: Optional[int]):
    """Start Celery worker and media server together.

    Deprecated: prefer separate ``eai telephony-worker`` and ``eai worker`` services
    (see docker-compose ``media`` + ``worker``).
    """
    import signal
    import atexit

    config_path = Path(config)
    if not config_path.exists():
        click.echo(f"❌ Config file not found: {config}", err=True)
        sys.exit(1)

    from app.config import load_config_from_file, settings

    load_config_from_file(str(config_path))

    media_proc = None
    celery_proc = None

    def cleanup():
        nonlocal media_proc, celery_proc
        for proc, label in ((media_proc, "media server"), (celery_proc, "Celery worker")):
            if proc is None or proc.poll() is not None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=5)
                click.echo(f"✅ {label} stopped")
            except Exception:
                proc.kill()

    atexit.register(cleanup)

    def _handle_signal(sig, frame):
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    port = media_port or settings.MEDIA_PORT
    media_proc = subprocess.Popen(
        ["eai", "telephony-worker", "--config", str(config_path), "--port", str(port)],
    )
    celery_proc = subprocess.Popen(
        ["celery", "-A", "app.workers.celery_app", "worker", f"--loglevel={loglevel}"],
    )
    click.echo(f"🚀 Started media server (pid={media_proc.pid}) and Celery worker (pid={celery_proc.pid})")

    try:
        while True:
            if media_proc.poll() is not None:
                click.echo("❌ Media server exited", err=True)
                break
            if celery_proc.poll() is not None:
                click.echo("❌ Celery worker exited", err=True)
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()


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
@click.option(
    "--force-rebuild",
    is_flag=True,
    default=False,
    help="Force rebuild of frontend without prompting",
)
@click.option(
    "--skip-migrations",
    is_flag=True,
    default=False,
    help="Skip running migrations before starting (not recommended)",
)
@click.option(
    "--worker-loglevel",
    "-l",
    default="info",
    type=click.Choice(["debug", "info", "warning", "error", "critical"], case_sensitive=False),
    help="Log level for Celery worker",
)
@click.option(
    "--imports-worker/--no-imports-worker",
    default=True,
    help=(
        "Also start a dedicated worker for the `imports` queue used by call "
        "import CSV processing (default: True). Disable to keep the previous "
        "single-worker behavior."
    ),
)
@click.option(
    "--imports-worker-concurrency",
    default=12,
    type=int,
    help=(
        "Concurrency for the imports+diarization+evaluations worker "
        "(default: 12; thread pool). Use lower values (8–12) when DB sharding "
        "is enabled; 32 threads can exhaust per-shard SQLAlchemy pools."
    ),
)
@click.option(
    "--telephony-worker/--no-telephony-worker",
    default=True,
    help="Spawn telephony media server for live voice WebSockets (default: on).",
)
@click.option(
    "--media-port",
    default=None,
    type=int,
    help="Telephony media server port (default: MEDIA_PORT / 8001).",
)
def start_all(
    config: str,
    host: Optional[str],
    port: Optional[int],
    build_frontend: bool,
    reload: bool,
    watch_frontend: bool,
    force_rebuild: bool,
    skip_migrations: bool,
    worker_loglevel: str,
    imports_worker: bool,
    imports_worker_concurrency: int,
    telephony_worker: bool,
    media_port: Optional[int],
):
    """Start the application server and Celery worker(s) together.

    By default this also spawns a telephony media server (``eai telephony-worker``)
    and a second Celery worker that consumes the ``imports`` queue (call-import CSV
    fan-out). Use --no-telephony-worker or --no-imports-worker to skip either.
    """
    import signal
    import atexit

    click.echo("🚀 Starting EfficientAI (App + Worker)...")
    if telephony_worker:
        click.echo("   Telephony media server will run on a separate port (SERVICE_MODE=media).")
    if imports_worker:
        click.echo(
            "   This will start the API server, the default Celery worker, "
            "and a dedicated worker for the `imports` queue."
        )
    else:
        click.echo("   This will start both the API server and Celery worker")
    click.echo("   Press Ctrl+C to stop all services\n")
    
    # Load configuration
    config_path = Path(config)
    if not config_path.exists():
        click.echo(f"❌ Config file not found: {config}", err=True)
        click.echo(f"💡 Create a config.yml file or use --config to specify a different path.", err=True)
        sys.exit(1)
    
    try:
        from app.config import load_config_from_file, settings
        load_config_from_file(str(config_path))
        click.echo(f"✅ Loaded configuration from {config_path}")
    except Exception as e:
        click.echo(f"❌ Error loading config: {e}", err=True)
        sys.exit(1)

    bind_media_port = media_port or settings.MEDIA_PORT
    if telephony_worker and not (settings.MEDIA_WS_BASE_URL or "").strip():
        settings.MEDIA_WS_BASE_URL = f"ws://localhost:{bind_media_port}"
        os.environ["MEDIA_WS_BASE_URL"] = settings.MEDIA_WS_BASE_URL

    os.environ["SERVICE_MODE"] = "api"
    
    # Store worker processes for cleanup.
    worker_process = None
    worker_imports_process = None
    telephony_process = None

    def _terminate(proc, label: str):
        """Best-effort terminate -> wait -> kill for a worker subprocess."""
        if proc is None or proc.poll() is not None:
            return
        try:
            click.echo(f"\n👋 Stopping {label}...")
            proc.terminate()
            proc.wait(timeout=5)
            click.echo(f"✅ {label} stopped")
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except Exception:
            pass

    def cleanup_processes():
        """Clean up spawned processes."""
        nonlocal worker_process, worker_imports_process, telephony_process
        _terminate(telephony_process, "Telephony media server")
        _terminate(worker_process, "Celery worker (default)")
        _terminate(worker_imports_process, "Celery worker (imports)")
    
    # Register cleanup on exit
    atexit.register(cleanup_processes)
    
    def signal_handler(sig, frame):
        """Handle Ctrl+C gracefully."""
        cleanup_processes()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize DB tables and run migrations before starting (unless explicitly skipped)
    if not skip_migrations:
        click.echo("🔄 Initializing database and running migrations...")
        from app.database import init_db
        from app.core.migrations import run_migrations, ensure_migrations_directory
        try:
            init_db()
            ensure_migrations_directory()
            run_migrations()
            click.echo("✅ Database initialized and migrations completed")
        except Exception as e:
            click.echo(f"❌ Migration failed: {e}", err=True)
            click.echo("💡 You can skip migrations with --skip-migrations (not recommended)", err=True)
            sys.exit(1)
    
    # Build frontend if needed
    if build_frontend:
        frontend_dir = Path(__file__).parent.parent / "frontend"
        if frontend_dir.exists():
            click.echo("🔨 Building frontend...")
            try:
                if not (frontend_dir / "node_modules").exists():
                    click.echo("   Installing frontend dependencies...")
                    subprocess.run(["npm", "install", "--legacy-peer-deps"], cwd=frontend_dir, check=True, capture_output=True)
                subprocess.run(["npm", "run", "build"], cwd=frontend_dir, check=True, capture_output=True)
                click.echo("✅ Frontend built successfully")
            except subprocess.CalledProcessError as e:
                click.echo(f"❌ Frontend build failed: {e}", err=True)
                sys.exit(1)
    
    # Start frontend watcher if requested
    frontend_watcher = None
    if watch_frontend:
        click.echo("👀 Starting frontend file watcher...")
        frontend_dir = Path(__file__).parent.parent / "frontend"
        frontend_watcher = start_frontend_watcher(frontend_dir)
    
    def _spawn_worker(args: list[str], label: str, prefix: str) -> subprocess.Popen:
        """Spawn a Celery worker subprocess and stream its stdout with a prefix."""
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        click.echo(f"✅ {label} started")

        def _stream():
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    if line:
                        click.echo(f"{prefix} {line.rstrip()}", err=False)
                proc.stdout.close()

        threading.Thread(target=_stream, daemon=True).start()
        return proc

    if telephony_worker:
        try:
            telephony_process = subprocess.Popen(
                [
                    "eai",
                    "telephony-worker",
                    "--config",
                    str(config_path),
                    "--port",
                    str(bind_media_port),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            click.echo(
                f"✅ Telephony media server started on port {bind_media_port} "
                f"(pid={telephony_process.pid})"
            )

            def _stream_telephony():
                if telephony_process.stdout:
                    for line in iter(telephony_process.stdout.readline, ""):
                        if line:
                            click.echo(f"[MEDIA] {line.rstrip()}", err=False)
                    telephony_process.stdout.close()

            threading.Thread(target=_stream_telephony, daemon=True).start()
        except FileNotFoundError:
            click.echo("❌ eai CLI not found for telephony-worker subprocess", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"❌ Failed to start telephony media server: {e}", err=True)
            sys.exit(1)

    # Start Celery workers as subprocess(es) with output streaming
    try:
        worker_process = _spawn_worker(
            [
                "celery",
                "-A",
                "app.workers.celery_app",
                "worker",
                f"--loglevel={worker_loglevel}",
                "-Q",
                "celery,audio-metrics",
                "-c",
                "8",
            ],
            label="Celery worker (celery + audio-metrics queues, concurrency=8)",
            prefix="[WORKER]",
        )

        if imports_worker:
            from app.workers.config import IMPORTS_WORKER_QUEUES

            worker_imports_process = _spawn_worker(
                [
                    "celery",
                    "-A",
                    "app.workers.celery_app",
                    "worker",
                    f"--loglevel={worker_loglevel}",
                    "-Q",
                    IMPORTS_WORKER_QUEUES,
                    "-P",
                    "threads",
                    "-c",
                    str(imports_worker_concurrency),
                ],
                label=(
                    f"Celery worker ({IMPORTS_WORKER_QUEUES} queues, "
                    f"pool=threads, concurrency={imports_worker_concurrency})"
                ),
                prefix="[WORKER-IMPORTS]",
            )
    except FileNotFoundError:
        click.echo("❌ Celery not found. Please install it: pip install celery", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Failed to start worker: {e}", err=True)
        sys.exit(1)
    
    # Small delay to let worker start
    time.sleep(1)
    
    # Start the application server in the main process
    # This allows uvicorn's reload to work properly (it needs to spawn child processes)
    try:
        from app.config import settings
        import uvicorn
        
        # Override with CLI options if provided
        if host:
            settings.HOST = host
        if port:
            settings.PORT = port
        
        click.echo("✅ Application server starting...")
        click.echo(f"   Host: {settings.HOST}")
        click.echo(f"   Port: {settings.PORT}")
        click.echo(f"   API: http://{settings.HOST}:{settings.PORT}{settings.API_V1_PREFIX}")
        click.echo(f"   Frontend: http://{settings.HOST}:{settings.PORT}/")
        click.echo(f"   Docs: http://{settings.HOST}:{settings.PORT}/docs")
        if watch_frontend:
            click.echo(f"   Frontend watcher: Active (rebuilding on file changes)")
        if imports_worker:
            from app.workers.config import IMPORTS_WORKER_QUEUES

            click.echo(
                f"   Workers: default queue + {IMPORTS_WORKER_QUEUES} "
                f"(concurrency={imports_worker_concurrency}; imports preferred)"
            )
        else:
            click.echo("   Workers: default queue only (--no-imports-worker)")
        if telephony_worker:
            click.echo(
                f"   Media WebSocket: {settings.MEDIA_WS_BASE_URL or f'ws://localhost:{bind_media_port}'}"
                f"{settings.API_V1_PREFIX}/telephony/vobiz/ws"
            )
        click.echo("\n📝 All services are running. Press Ctrl+C to stop.\n")
        
        # Run uvicorn in the main process (allows reload to work)
        uvicorn.run(
            "app.main:app",
            host=settings.HOST,
            port=settings.PORT,
            reload=reload,
        )
    except KeyboardInterrupt:
        pass
    except Exception as e:
        click.echo(f"❌ App error: {e}", err=True)
    finally:
        cleanup_processes()
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


def _bootstrap_sharding_config(config_path: str) -> None:
    from app.config import load_config_from_file
    from app.db_sharding.pool_manager import db_pool_manager

    load_config_from_file(config_path)
    db_pool_manager.reset()


@click.group()
def sharding():
    """Call-import data-plane sharding admin (rebalance / registry)."""
    pass


main.add_command(sharding)


@sharding.command("list-slices")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, readable=True),
    default="config.yml",
    help="Path to configuration YAML file",
)
@click.option(
    "--call-import-id",
    required=True,
    help="Call import UUID whose slice registry to inspect",
)
def sharding_list_slices(config: str, call_import_id: str):
    """Show catalog slice registry rows for a call import."""
    from uuid import UUID

    from app.db_sharding.pool_manager import open_catalog_session
    from app.db_sharding.rebalance import RebalanceError, list_shard_slices, require_sharding_enabled

    try:
        _bootstrap_sharding_config(config)
        require_sharding_enabled()
        cid = UUID(call_import_id)
    except (ValueError, RebalanceError) as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)

    catalog = open_catalog_session()
    try:
        slices = list_shard_slices(catalog, cid)
        if not slices:
            click.echo(f"No registry slices for call_import {cid}")
            return
        click.echo(f"call_import_id: {cid}")
        click.echo(f"slices: {len(slices)}")
        for item in slices:
            click.echo(
                f"  slice {item.slice_id}: shard={item.shard_id} "
                f"rows [{item.row_index_min}, {item.row_index_max}] "
                f"(count={item.row_count})"
            )
    finally:
        catalog.close()


@sharding.command("rebalance-slices")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, readable=True),
    default="config.yml",
    help="Path to configuration YAML file",
)
@click.option("--call-import-id", required=True, help="Call import UUID to rebalance")
@click.option("--from-shard", required=True, help="Source shard id (e.g. data-shard-01)")
@click.option("--to-shard", required=True, help="Target shard id (e.g. data-shard-02)")
@click.option(
    "--slice-id",
    "slice_ids",
    multiple=True,
    type=int,
    help="Move only these slice ids (default: all slices on --from-shard)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Plan only: print row counts without copying or updating registry",
)
@click.option(
    "--force",
    is_flag=True,
    help="Skip quiescence checks (use only after pausing workers)",
)
def sharding_rebalance_slices(
    config: str,
    call_import_id: str,
    from_shard: str,
    to_shard: str,
    slice_ids: tuple[int, ...],
    dry_run: bool,
    force: bool,
):
    """Copy call-import slice rows (and eval rows) from one shard to another."""
    from uuid import UUID

    from app.db_sharding.pool_manager import open_catalog_session
    from app.db_sharding.rebalance import (
        RebalanceError,
        require_sharding_enabled,
        build_rebalance_plan,
        execute_rebalance_slices,
    )

    try:
        _bootstrap_sharding_config(config)
        require_sharding_enabled()
        cid = UUID(call_import_id)
    except (ValueError, RebalanceError) as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)

    catalog = open_catalog_session()
    try:
        plan = build_rebalance_plan(
            catalog,
            cid,
            from_shard_id=from_shard,
            to_shard_id=to_shard,
            slice_ids=slice_ids or None,
        )
        click.echo("Rebalance plan:")
        click.echo(f"  call_import_id: {plan.call_import_id}")
        click.echo(f"  from_shard:     {plan.from_shard_id}")
        click.echo(f"  to_shard:       {plan.to_shard_id}")
        click.echo(f"  slices:         {len(plan.slices)}")
        for item in plan.slices:
            click.echo(
                f"    slice {item.slice_id}: rows [{item.row_index_min}, {item.row_index_max}]"
            )
        click.echo(f"  import_rows:    {plan.import_row_count}")
        click.echo(f"  eval_rows:      {plan.eval_row_count}")

        result = execute_rebalance_slices(
            catalog,
            plan,
            dry_run=dry_run,
            force=force,
        )
        if result.dry_run:
            click.echo("✅ Dry run complete (no changes made)")
        else:
            click.echo(
                "✅ Rebalance complete: "
                f"slices={result.slices_moved}, "
                f"import_rows={result.import_rows_moved}, "
                f"eval_rows={result.eval_rows_moved}"
            )
    except RebalanceError as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)
    finally:
        catalog.close()


if __name__ == "__main__":
    main()

