# The Quiet Page

A book café whose AI agents read supplier invoices and customer emails and move money, inside two boundaries:

- **Sandbox (code):** the Reader agent's own extraction code runs in a throwaway container with no network,
  a read-only filesystem and memory/CPU/process/time caps (gVisor on the Vultr VM).
- **Counterfoil (money):** a deterministic payment gate; a refund or charge whose amount, recipient or record does
  not match the books is held for a human.

Built for the Vultr Agent Rush hackathon (Blast Radius Zero). Work in progress.

## How Vultr is used

| Piece | Vultr product | What it does here |
|---|---|---|
| Demo host | **Vultr Cloud Compute VM** (Ubuntu 24.04) | Runs the FastAPI demo behind Caddy (HTTPS), and the Docker daemon the sandbox uses. |
| Sandbox runtime | gVisor (`runsc`) on that VM | Every parser the Reader agent writes runs in a fresh container under gVisor: no network, read-only filesystem, memory/CPU/process/time caps, no capabilities, unprivileged user. |
| Payment rail | Braintree **sandbox** | Refunds the gate approves really execute there (`DEMO_RAIL=braintree`); the page shows the sandbox transaction ids. Without the keys a simulated rail is used, and the page says so. |
| Agents' model | **Vultr Serverless Inference** (OpenAI-compatible, `https://api.vultrinference.com/v1`) | Both agents (Ivy the Reader, Milo the payments agent) call it; preset `vultr` in `counterfoil/llm.py`, model from `VULTR_MODEL`. |

The keys (inference, Braintree sandbox) live only in `/etc/quiet-page.env` on the VM (mode 600), never in the repo.

### Deploy

```bash
deploy/push.sh root@<vm-ip>        # copies the repo, installs Docker + gVisor + Caddy, starts the service
ssh root@<vm-ip> 'nano /etc/quiet-page.env && systemctl restart quiet-page'   # put the inference key in
```

The page is then served at `https://<ip-with-dashes>.sslip.io` (or set `DOMAIN=` before running the setup).
Without a key the page still works: model cases answer from recorded real runs (labelled as such), and the
compromised-model drills always run live in the sandbox.
