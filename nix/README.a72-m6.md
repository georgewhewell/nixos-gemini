# A72 CI9 M6 clock diagnostics

M6 retains M5 device-tree activation, preflight gates and CPU online policy.
Its kernel adds rate-limited diagnostics to existing clock observation failure
paths: snapshot status, decoder status with reference rate and valid raw
register sample, and missing clock parents. It takes no additional samples and
changes no clock, voltage or CPU admission policy. The native build runs tests
of the actual callbacks with injected failures.

M5 reached full NixOS but failed A72 resource binding because MP2 rate was zero;
all observed CPU clock outputs were zero. The new messages distinguish the
failure stages; they do not establish or fix the underlying cause. CPU8/9 stay
offline and cellular acceptance still requires successful A72 preflight.

See README.a72-m5.md for inherited integration constraints. M6 uses the unique
GEMINI_A72_CI9_M6 boot token and the exact kernel revision pinned in flake.nix.
