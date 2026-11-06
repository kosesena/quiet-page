# The Quiet Page

A book café whose AI agents read supplier invoices and customer emails and move money, inside two boundaries:

- **Sandbox (code):** the Reader agent's own extraction code runs in a throwaway container with no network,
  a read-only filesystem and memory/CPU/process/time caps (gVisor on the Vultr VM).
- **Counterfoil (money):** a deterministic payment gate; a refund or charge whose amount, recipient or record does
  not match the books is held for a human.

Built for the Vultr Agent Rush hackathon (Blast Radius Zero). Work in progress.
