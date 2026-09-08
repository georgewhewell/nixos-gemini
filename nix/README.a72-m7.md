# A72 CI9 M7 cold admission

M7 preserves M6 device tree and kernel configuration apart from the unique
GEMINI_A72_CI9_M7 token. Its kernel decodes divider0 and the exact cold MP2
clk26m/PLL0 tuple, validates supplier/CCF identity and a fresh cold snapshot
at probe and immediately before CPU8 rail/reset preparation. Secure PSCI
retains initial PLL programming ownership. The kernel core, API and callback
host tests run during native kernel configuration.

The required read-only helper checks the new cold-clk26m-v1 transcript,
26MHz path and zero PLL. It resolves each regulator by exact DT node and
checks the descriptor name, then validates A72 supply phandles and existing
voltage/BUCKB-off/SRAM selector constraints. No DT/regulator initialization
change is needed. The A72 helper PATH now includes diffutils for binary
phandle comparison. Tests cover clock contract and provider identity failures.

This is a preflight candidate: CPU8/9 remain offline, maxcpus8, and no automatic
CPU_ON is added. Passing preflight does not qualify CPU startup or a running
clock. A later supervised startup transaction must check actual completion
and post-start clock state with recovery armed.
