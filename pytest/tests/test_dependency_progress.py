"""Progress storms cannot create an unbounded GUI backlog or lose completion."""
from threading import Thread

from wayfinder.runtime.dependency_progress import DependencyProgress


def test_progress_storm_is_coalesced_and_completion_preserved():
    updates = DependencyProgress()
    for i in range(100000):
        updates.put(('progress', i, 100000, f'Resolving {i}'))
    updates.put(('done', 0))
    updates.put(('progress', 0, 1, 'late update'))
    assert updates.take() == [('progress', 99999, 100000, 'Resolving 99999'), ('done', 0)]
    assert updates.take() == []


def test_concurrent_producer_preserves_crash_and_bounded_poll_work():
    updates = DependencyProgress()
    def produce():
        for i in range(20000):
            updates.put(('progress', i, 20000, 'Installing'))
        updates.put(('crash', 'OSError', 'Disk full'))
    worker = Thread(target=produce)
    worker.start()
    received = []
    while worker.is_alive():
        batch = updates.take()
        assert len(batch) <= 2
        received.extend(m for m in batch if m[0] != 'progress')
    worker.join()
    received.extend(m for m in updates.take() if m[0] != 'progress')
    assert received == [('crash', 'OSError', 'Disk full')]


def test_new_progress_arrives_after_empty_poll():
    updates = DependencyProgress()
    assert updates.take() == []
    updates.put(('progress', 1, 3, 'Downloading'))
    assert updates.take() == [('progress', 1, 3, 'Downloading')]
    updates.put(('done', 1))
    assert updates.take() == [('done', 1)]
