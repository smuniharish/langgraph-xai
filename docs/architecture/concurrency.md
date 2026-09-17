# Concurrency

## Kid-level view

Concurrency means several graph moments happen at once; each still needs its
own numbered place.

## Production view

Bound per-runtime work with `max_concurrency`, use stable run/node IDs and
sequence or parent links, and make adapter operations idempotent where
retries are possible. Do not rely on arrival order for causal order.

## Why and example

Two parallel nodes can emit evidence independently and join at a decision.
The canonical model preserves both parents even if exporters finish later.

## Common mistakes

Avoid unbounded queues, shared mutable global configuration, duplicate writes
without idempotency, and treating wall-clock order as graph order.

