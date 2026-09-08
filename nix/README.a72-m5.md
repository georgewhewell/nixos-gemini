# M5: A72 admission on the CI9 system

This separate candidate retains CI9 cellular, filesystem, watchdog, display
and input integration. It adds the previously reviewed CPU8 online control
and CPU9-after-CPU8 admission commits, three provider config options and a
checked A72 DT composition. maxcpus=8 keeps the A72s offline at startup;
there is no automatic CPU_ON, frequency change or hot-unplug action.

The DT transformer starts from the completed cellular/platform DT, restores
/chosen byte-for-byte and refuses any delta outside the named A72 statuses
and enable-methods. It preserves the complete node set. A53 OPP tables are
disabled; CPU_FREQ remains off. The actual CI9 CPU nodes omit status, rather
than declaring disabled. Duplicate composition is refused using the disabled
provider preconditions. Negative tests prove rejection leaves input intact.

The read-only A72 service runs after watchdog takeover and must pass before
cellular startup and baseline acceptance. It checks offline CPUs, provider
binding/logs, voltages, clock consistency and absence of A72 errors. Its
result is /run/gemini-a72-preflight/result. The inherited preflight requirements
are deliberately retained, including its observed MP2 clock window; a new
hardware mismatch must be investigated rather than silently accepted.

The previous M1–M4 candidates failed before SSH without an established exact
failure boundary. This candidate narrows the configuration difference by
starting from accepted CI9; it is not an established fix. Build success and
provider preflight do not qualify CPU_ON. Any later CPU8/CPU9 attempt needs
live supervised recovery and exact current boot/image guards, before the
supervisor is disarmed. No A72 power-off path is claimed.
