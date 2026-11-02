# Request: make the concurrency tests prove the interleaving they claim

`ClickDeletionRaceTest` checks that click recording, deletion and expiry changes on the same link
are serialized by the link's row lock. Each test starts a first operation inside a transaction,
waits until it holds the lock, then starts a second operation and sleeps 300 ms before letting the
first one commit, so that the second one should be waiting on the lock meanwhile.

Nothing checks that it actually was. On a slow or busy machine the second operation can start
after the first has already committed; the test then passes without having exercised the race it
names. A test that can pass without testing anything is worse than a failing one, because nobody
notices.

## Wanted
- Every test in `ClickDeletionRaceTest` proves that the intended interleaving happened, and fails
  (not passes) if it did not.
- The tests keep asserting the same outcomes they assert today.
- They stay fast and deterministic on a normal machine; a fixed sleep must not be what makes them
  correct.
- Production code does not change: this is a test-quality improvement.
