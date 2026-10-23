"""Shared test doubles: an in-process FakeRedis.

Implements exactly the commands the codebase uses (strings with TTL,
sorted sets, lists, transactional pipelines, scan). No server, no extra
dependency - hermetic and deterministic.

If you add a Redis command to production code, add it here (and keep the
semantics faithful: blocking pops return None when the source list is
empty instead of blocking, because tests never rely on real blocking).
"""

from __future__ import annotations


class FakePipe:
    def __init__(self, store: FakeRedis) -> None:
        self._store = store
        self._ops: list[tuple[str, tuple]] = []

    def zadd(self, key: str, mapping: dict) -> FakePipe:
        self._ops.append(("zadd", (key, mapping)))
        return self

    def zremrangebyscore(self, key: str, lo: str, hi: float) -> FakePipe:
        self._ops.append(("zrem", (key, lo, hi)))
        return self

    def zcard(self, key: str) -> FakePipe:
        self._ops.append(("zcard", (key,)))
        return self

    def expire(self, key: str, ttl: int) -> FakePipe:
        self._ops.append(("expire", (key, ttl)))
        return self

    async def execute(self) -> list:
        results = []
        for op, args in self._ops:
            if op == "zadd":
                key, mapping = args
                self._store.zsets.setdefault(key, []).extend(mapping.items())
                results.append(True)
            elif op == "zrem":
                key, _, hi = args
                bucket = self._store.zsets.get(key, [])
                self._store.zsets[key] = [(m, s) for (m, s) in bucket if s > hi]
                results.append(True)
            elif op == "zcard":
                (key,) = args
                results.append(len(self._store.zsets.get(key, [])))
            elif op == "expire":
                results.append(True)
        self._ops.clear()
        return results


class FakeRedis:
    """Just enough Redis for rate limiting + the job queue."""

    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.zsets: dict[str, list[tuple[str, float]]] = {}
        self.ttls: dict[str, int] = {}

    # --- connection -----------------------------------------------------

    async def ping(self) -> bool:
        return True

    def pipeline(self, transaction: bool = True) -> FakePipe:
        return FakePipe(self)

    # --- strings ----------------------------------------------------------

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def set(self, key: str, value, ex: int | None = None) -> bool:
        self.strings[key] = value if isinstance(value, str) else str(value)
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            for store in (self.strings, self.lists, self.zsets, self.ttls):
                if key in store:
                    del store[key]
                    n += 1
        return n

    # --- lists ------------------------------------------------------------

    async def lpush(self, key: str, *values: str) -> int:
        bucket = self.lists.setdefault(key, [])
        bucket[0:0] = list(values)
        return len(bucket)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        bucket = self.lists.get(key, [])
        if stop == -1:
            return list(bucket[start:]) if start else list(bucket)
        return list(bucket[start : stop + 1])

    async def lrem(self, key: str, count: int, value: str) -> int:
        bucket = self.lists.get(key, [])
        if count == 1:
            try:
                bucket.remove(value)
                return 1
            except ValueError:
                return 0
        raise NotImplementedError("FakeRedis.lrem only supports count=1")

    async def brpoplpush(self, src: str, dst: str, timeout: int = 0) -> str | None:
        source = self.lists.get(src, [])
        if not source:
            return None
        value = source.pop()  # right end
        self.lists.setdefault(dst, []).insert(0, value)
        return value

    # --- scan ---------------------------------------------------------------

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in list(self.strings) + list(self.lists) + list(self.zsets):
            if key.startswith(prefix):
                yield key
