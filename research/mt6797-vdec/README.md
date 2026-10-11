# MT6797 H.264 controls and fixtures

This directory contains the original GPL-2.0-only translation of Linux
stateless H.264 controls, independent host tests, and original generated
fixtures used by the [maintained V4L2 Request decoder](../mt6797-vdec-v4l2/README.md).
The decoder register backend, native capture buffers and V4L2 queues live there.

Run the shared control tests against the maintained kernel's public ABI:

```sh
CC=gcc bash research/mt6797-vdec/test.sh /path/to/linux
```

The four early probe modules and their Kbuild have been retired from the
maintained tree. Their complete [source](https://github.com/georgewhewell/nixos-gemini/tree/ef79a94a7f985fd15a518c77aae6d411fd5eadf0/research/mt6797-vdec)
and [historical README](https://github.com/georgewhewell/nixos-gemini/blob/ef79a94a7f985fd15a518c77aae6d411fd5eadf0/research/mt6797-vdec/README.md)
remain available at pinned commit `ef79a94a7f985fd15a518c77aae6d411fd5eadf0`.
Retained trial artifacts and the historical interface ledger are unchanged.
Historical polling results do not qualify the current IRQ decoder; see its
maintained README for the measured scope and remaining completion contract.
