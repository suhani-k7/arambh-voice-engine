import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

class AppLogger:
    _instance = None

    @classmethod
    def get_instance(cls) -> logging.Logger:
        if cls._instance is None:
            cls._instance = cls._setup_logger()
        return cls._instance

    @staticmethod
    def _setup_logger() -> logging.Logger:
        logger = logging.getLogger("ArambhVoiceEngine")
        logger.setLevel(logging.INFO)
        if logger.handlers: return logger

        log_directory = Path(__file__).resolve().parent.parent / "logs"
        os.makedirs(log_directory, exist_ok=True)
        
        telemetry_format = logging.Formatter(
            fmt='%(asctime)s.%(msecs)03d | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(telemetry_format)
        logger.addHandler(console_handler)

        file_handler = RotatingFileHandler(filename=log_directory / "app.log", maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        file_handler.setFormatter(telemetry_format)
        logger.addHandler(file_handler)
        return logger