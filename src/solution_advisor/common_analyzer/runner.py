from __future__ import annotations
import time
import redis
from solution_advisor.artifacts import LocalArtifactStorage, S3ArtifactStorage
from solution_advisor.common_analyzer.queue import RedisAnalysisQueue
from solution_advisor.common_analyzer.service import AnalysisService
from solution_advisor.config import Settings
from solution_advisor.persistence.database import make_session_factory

def storage(settings):
    if settings.storage_backend == "local": return LocalArtifactStorage(settings.storage_root)
    import boto3
    return S3ArtifactStorage(boto3.client("s3", endpoint_url=settings.s3_endpoint_url, aws_access_key_id=settings.s3_access_key_id, aws_secret_access_key=settings.s3_secret_access_key), bucket=settings.s3_bucket, prefix=settings.s3_prefix)

def main():
    settings = Settings.from_env(); queue = RedisAnalysisQueue(redis.from_url(settings.redis_url)); factory = make_session_factory(settings.database_url)
    while True:
        session = factory(); service = AnalysisService(session, storage(settings), queue); service.recover(); queue.heartbeat({"instance_id":"common-analyzer","status":"READY","image_ref":"solution-advisor-common-analyzer","max_concurrency":1})
        task_id = queue.take(2)
        if task_id: service.run(task_id)
        session.close(); time.sleep(0.1)

if __name__ == "__main__": main()
