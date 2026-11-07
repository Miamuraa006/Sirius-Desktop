# Files integration

`Handler` validates canonical local paths independently of the router/core.
Destination overwrite is ALWAYS refused, even after confirmation.

Before dispatching a confirmed trash, outside-root, or cross-root operation,
core must set ONE invocation-scoped, private grant in `Context.data`:

```python
context.data['file_grant'] = tuple(str(p) for p in (path, destination) if p is not None)
```

Only server-side confirmation logic may set this; never copy it from intent
parameters. Handler consumes the grant with `pop`, compares exact canonical
paths/action, and still rejects protected directories, UNC/device/ADS,
reparse ancestors, root mutation, existing destination, and invalid paths.
Without the grant it returns `needs_confirmation` and safe canonical details.
The core owns expiry, same-session checks, pending intent retention and the
single-use `подтверждаю` / `отмена` conversation. Clear any remaining grant in
core's dispatch `finally` too (validation can return before consumption).

Native moves use `MoveFileExW(COPY_ALLOWED)` without `REPLACE_EXISTING`.
Windows can reject cross-volume directory moves; errors are reported, never
worked around by permanent deletion. Trash exclusively uses send2trash.
Opening documents/folders is successful only after observing a matching
Explorer directory or a visible PID-bound document window. Singleton apps
without an observable process/document can open but return `unsupported`.
