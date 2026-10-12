import taskiq_fastapi
from taskiq import TaskiqState
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# We use Redis for both brokering tasks and storing results.
redis_url = "redis://localhost:6379/0"

broker = ListQueueBroker(
    redis_url,
).with_result_backend(
    RedisAsyncResultBackend(redis_url)
)

taskiq_fastapi.init(broker, "main:app")
