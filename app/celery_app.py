"""Celery worker configuration; Redis carries job IDs, SQLite stores results."""
import os

from celery import Celery

celery_app = Celery(
    "geospatial_api",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    include=["app.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=5,
    broker_transport_options={"socket_connect_timeout": 5, "socket_timeout": 5},
)
