import asyncio

from src.services.jobs import JobManager


async def test_job_manager_reports_successful_result():
    manager = JobManager()

    async def work():
        await asyncio.sleep(0)
        return {"changes": ["basic_info"]}

    job = manager.submit("soul_import", work())
    await manager.wait(job.id)
    finished = manager.get(job.id)

    assert finished.status == "completed"
    assert finished.result == {"changes": ["basic_info"]}


async def test_job_manager_reports_failure_without_leaking_private_error():
    manager = JobManager()

    async def work():
        raise ValueError("bad import")

    job = manager.submit("soul_import", work())
    await manager.wait(job.id)
    failed = manager.get(job.id)

    assert failed.status == "failed"
    assert failed.error == "ValueError: 任务执行失败"
    assert "bad import" not in failed.error


async def test_shutdown_cancels_running_jobs():
    manager = JobManager()
    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.Event().wait()

    job = manager.submit("long", work())
    await started.wait()
    await manager.shutdown()

    assert manager.get(job.id).status == "cancelled"
