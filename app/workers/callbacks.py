import structlog
from celery.signals import task_failure, task_success, task_prerun

logger = structlog.get_logger()


@task_prerun.connect
def on_task_prerun(task_id, task, args, kwargs, **extras):
    logger.info("Task started", task_id=task_id, task_name=task.name)


@task_success.connect
def on_task_success(sender, result, **kwargs):
    logger.info("Task succeeded", task_name=sender.name)


@task_failure.connect
def on_task_failure(sender, task_id, exception, traceback, **kwargs):
    logger.error(
        "Task failed",
        task_id=task_id,
        task_name=sender.name,
        error=str(exception),
    )
