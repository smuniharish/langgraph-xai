# Failure handling

## Kid-level view

If the note-taker fails, the graph should follow a clearly chosen rule rather
than pretending the note was written.

## Production view

Configure fail-open or fail-closed per runtime and boundary, surface policy,
storage, and exporter errors, and preserve correlation for retries. A
successful graph result must not be reported as a successful explanation
export unless both succeeded.

## Why and example

Fail-open may protect user-facing availability while recording an explicit
missing-artifact status; fail-closed may be required where explainability is a
release gate. Test both modes.

## Common mistakes

Do not swallow adapter exceptions, silently return complete-looking artifacts,
or retry non-idempotent writes without a key.

