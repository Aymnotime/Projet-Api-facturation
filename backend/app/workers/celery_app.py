"""Celery worker configuration for billing tasks."""
import os
from celery import Celery

def make_celery() -> Celery:
    """Create Celery app with FastAPI-compatible settings."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    celery_app = Celery(
        "billing_worker",
        broker=redis_url,
        backend=redis_url,
        include=["app.tasks.invoice_tasks", "app.tasks.webhook_tasks"],
    )
    
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_time_limit=300,
        task_soft_time_limit=240,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        broker_connection_retry_on_startup=True,
        # Retry settings
        task_default_retry_delay=60,
        task_max_retries=5,
    )
    
    return celery_app

celery_app = make_celery()
