"""Tests for Redis fixes: stream MAXLEN, FakeRedis xadd, TTL on keys."""

import pytest

from app.utils.redis_client import FakeRedis


class TestFakeRedisXadd:
    """Verify FakeRedis.xadd supports maxlen parameter."""

    @pytest.mark.asyncio
    async def test_xadd_basic(self):
        r = FakeRedis()
        entry_id = await r.xadd("mystream", {"key": "value"})
        assert entry_id is not None
        assert "mystream" in r._store
        assert len(r._store["mystream"]) == 1

    @pytest.mark.asyncio
    async def test_xadd_maxlen_trims(self):
        """When maxlen=3, adding a 4th entry should trim the oldest."""
        r = FakeRedis()
        for i in range(5):
            await r.xadd("mystream", {"i": str(i)}, maxlen=3)
        assert len(r._store["mystream"]) == 3
        # Oldest entries (0, 1) should be trimmed; remaining: 2, 3, 4
        remaining = [entry["i"] for entry in r._store["mystream"]]
        assert remaining == ["2", "3", "4"]

    @pytest.mark.asyncio
    async def test_xadd_no_maxlen(self):
        """Without maxlen, all entries should be kept."""
        r = FakeRedis()
        for i in range(10):
            await r.xadd("mystream", {"i": str(i)})
        assert len(r._store["mystream"]) == 10

    @pytest.mark.asyncio
    async def test_xadd_maxlen_1(self):
        """maxlen=1 should keep only the latest entry."""
        r = FakeRedis()
        for i in range(5):
            await r.xadd("mystream", {"i": str(i)}, maxlen=1)
        assert len(r._store["mystream"]) == 1
        assert r._store["mystream"][0]["i"] == "4"

    @pytest.mark.asyncio
    async def test_xadd_returns_entry_id(self):
        r = FakeRedis()
        eid1 = await r.xadd("s", {"a": "1"})
        eid2 = await r.xadd("s", {"a": "2"})
        assert eid1 != eid2
        assert eid1.endswith("-0")
        assert eid2.endswith("-0")


class TestFakeRedisPipeline:
    """Verify FakeRedis pipeline supports xadd with maxlen."""

    @pytest.mark.asyncio
    async def test_pipeline_xadd(self):
        r = FakeRedis()
        async with r.pipeline(transaction=True) as pipe:
            pipe.xadd("stream", {"k": "v"}, maxlen=100)
            await pipe.execute()
        assert "stream" in r._store
        assert len(r._store["stream"]) == 1

    @pytest.mark.asyncio
    async def test_pipeline_xadd_maxlen_trims(self):
        r = FakeRedis()
        async with r.pipeline(transaction=True) as pipe:
            for i in range(5):
                pipe.xadd("stream", {"i": str(i)}, maxlen=3)
            await pipe.execute()
        assert len(r._store["stream"]) == 3

    @pytest.mark.asyncio
    async def test_pipeline_mixed_ops(self):
        """Pipeline with xadd + hset + expire should all work."""
        r = FakeRedis()
        async with r.pipeline(transaction=True) as pipe:
            pipe.hset("myhash", mapping={"a": "1"})
            pipe.expire("myhash", 300)
            pipe.xadd("mystream", {"k": "v"}, maxlen=10)
            await pipe.execute()
        assert "myhash" in r._store
        assert "mystream" in r._store
        assert len(r._store["mystream"]) == 1
