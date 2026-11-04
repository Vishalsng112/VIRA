import asyncio
from contextlib import contextmanager
from loguru import logger
import sys
import signal
import os
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

    app = create_app(kernel)

    config = uvicorn.Config(
        app=app,
        host=os.getenv("VIRA_HOST", "0.0.0.0"),
        port=int(os.getenv("VIRA_PORT", "8000")),
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("VIRA_TRUSTED_PROXIES", "127.0.0.1"),
    )
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