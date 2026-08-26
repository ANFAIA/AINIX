"""Print throughput from a chat-completions response on stdin."""

import json
import sys

d = json.load(sys.stdin)
t = d.get("timings")
if t:
    print(f"prompt      {t['prompt_per_second']:8.1f} tok/s")
    print(f"generation  {t['predicted_per_second']:8.1f} tok/s  ({t['predicted_n']} tokens)")
else:
    print("engine reported no timings; usage:", d.get("usage", {}))
