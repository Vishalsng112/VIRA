import asyncio
from contextlib import contextmanager
from loguru import logger
import sys
import signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from vira.kernel import Kernel
from vira.api.app import create_app
from vira.auth import auth, database

# logger.remove()  # Remove default handler
# logger.add(
#     sys.stderr,
#     colorize=True,
#     format="<level>{level:<8}</level> | {name}:{function}:{line} - <level>{message}</level>"
# )


# Initialize database tables before anything else
database.init_db()


class SignalAwareServer(uvicorn.Server):
    """Use the application's asyncio signal handlers instead of Uvicorn's."""

    @contextmanager
    def capture_signals(self):
        yield


async def main():
    kernel = Kernel(config_path="config.yaml")
    await kernel.boot()

    # Generate new recovery code for admin on each startup (so it appears in logs)
    if auth.admin_exists():
        admin_username = auth.get_admin_username()
        if admin_username:
            new_code = auth.generate_recovery_code()
            new_hash = auth.hash_recovery_code(new_code)
            auth.update_recovery_code(admin_username, new_hash)
            logger.info(f"🔐 Recovery code for '{admin_username}': {new_code}")
            logger.info("   (Use this code on the 'Forgot password' page to reset your password)")

    app = create_app(kernel)

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8000, log_level="info")
    server = SignalAwareServer(config)
    loop = asyncio.get_running_loop()

    def handle_signal(signum: int) -> None:
        logger.info("Shutdown signal received")
        server.handle_exit(signum, None)

    loop.add_signal_handler(signal.SIGINT, handle_signal, signal.SIGINT)
    loop.add_signal_handler(signal.SIGTERM, handle_signal, signal.SIGTERM)

    try:
        await server.serve()
    finally:
        logger.info("Initiating shutdown...")
        await kernel.shutdown()
        logger.info("VIRA shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())