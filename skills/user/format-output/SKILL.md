# format-output

Render a result for a terminal that may be 80 columns and may have no colour.

## Procedure

1. Wrap to `$COLUMNS`, falling back to 80. Never emit a line that wraps in the
   middle of a path or a command — break before it instead.
2. Colour is decoration, never information. If `NO_COLOR` is set or stdout is
   not a tty, drop every escape and the output must still be complete.
3. Truncate long output at the **end**, not the middle, and say how much was
   dropped: `… 412 more lines`. A user who cannot tell that output was cut will
   act on a partial answer.
4. Tables only when every row has the same fields. Otherwise a list.
5. Commands the user might run go on their own line, unindented and unwrapped,
   so they can be copied without repair.
