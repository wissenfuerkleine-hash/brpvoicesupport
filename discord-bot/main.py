"""
Main entry point.
Starts the Discord bot and the FastAPI server concurrently.
"""

import asyncio
import os
import uvicorn
from bot.client import create_bot
from api.main import app
from config.settings import settings
from utils.logger import logger, setup_logger

# Ensure log directory exists
os.makedirs("logs", exist_ok=True)

# Re-initialize logger with settings
setup_logger(log_file=settings.log_file, level=settings.log_level)


async def run_api():
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info("Starting API server on port %d", settings.port)
    await server.serve()


async def run_bot():
    bot = create_bot()
    logger.info("Starting Discord bot...")
    try:
        await bot.start(settings.discord_token)
    except Exception as e:
        logger.critical("Bot crashed: %s", e, exc_info=True)
        raise


async def main():
    logger.info("=" * 60)
    logger.info("  Discord Security & Moderation Bot  v1.0.0")
    logger.info("=" * 60)
    logger.info("Environment: %s", settings.environment)
    logger.info("API Port: %d", settings.port)

    await asyncio.gather(
        run_api(),
        run_bot(),
        return_exceptions=False,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        raise
