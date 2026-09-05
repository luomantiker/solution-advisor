from __future__ import annotations
import json

QUEUE_KEY = "solution-advisor:analysis:queue"
HEARTBEAT_KEY = "solution-advisor:workers:common-analyzer"

class RedisAnalysisQueue:
    def __init__(self, client): self.client = client
    def enqueue(self, task_id: str): self.client.lpush(QUEUE_KEY, json.dumps({"task_id": task_id}))
    def take(self, timeout: int = 1) -> str | None:
        value = self.client.brpop(QUEUE_KEY, timeout=timeout)
        return json.loads(value[1])["task_id"] if value else None
    def heartbeat(self, payload: dict): self.client.set(HEARTBEAT_KEY, json.dumps(payload), ex=30)
