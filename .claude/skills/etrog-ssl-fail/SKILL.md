---
name: etrog-ssl-fail
description: >-
  Use this when Python code, pip, or the test suite in this project fails with
  SSL/TLS certificate errors (e.g. "SSLError", "CERTIFICATE_VERIFY_FAILED",
  "unable to get local issuer certificate", "self-signed certificate in
  certificate chain") — typically caused by the Etrog corporate filtering proxy
  that inspects HTTPS traffic. It installs `truststore` and drops a
  `sitecustomize.py` into the project's virtualenv so Python verifies TLS
  against the Windows certificate store (where Etrog's root CA lives) instead of
  the bundled `certifi` list. Trigger phrases: "SSL error", "certificate verify
  failed", "Etrog is blocking my requests", "self-signed certificate in chain".
---

# Fix Etrog SSL / certificate errors

## What's going on

"Etrog" is a corporate TLS-inspecting proxy. It intercepts HTTPS connections and
re-signs them with a **corporate root CA**. That CA is installed in the
**Windows certificate store**, but Python (and `pip`, `requests`, `httpx`, etc.)
verify TLS against their own bundled `certifi` CA list, which does **not** contain
it. So every outbound HTTPS call from Python fails with something like:

- `ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate`
- `... self-signed certificate in certificate chain`

The [`truststore`](https://truststore.readthedocs.io/) package makes Python verify
against the **OS trust store** (Windows CryptoAPI) instead, where Etrog's root CA
already lives — so the corporate cert is trusted and the errors disappear.

Dropping the call in a `sitecustomize.py` inside the venv means Python runs it
**automatically at interpreter startup** for every process using that venv — no
code changes, no per-script imports.

## The fix

Run these from the **project root** (`rf-component-finder/`), with the project
virtualenv (`.venv`) active or present. Commands are PowerShell (the team is on
Windows).

### 1. Install `truststore` into the venv

```powershell
.\.venv\Scripts\python.exe -m pip install truststore
```

> **Bootstrap trap:** if Etrog is *already* blocking SSL, this `pip install` may
> itself fail with the same certificate error (chicken-and-egg — you need
> truststore to fix pip, but pip is what's broken). If so, do the one-time
> install with the trusted-host escape hatch, then proceed normally:
>
> ```powershell
> .\.venv\Scripts\python.exe -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org truststore
> ```
>
> (`--trusted-host` skips TLS verification for *these hosts only, this one
> command only*. The permanent fix below is what actually secures things.)

`truststore` requires **Python 3.10+** (it is a pure-Python package with no
compiled dependencies).

### 2. Create `sitecustomize.py` in the venv's `site-packages`

Create the file at:

```
.venv\Lib\site-packages\sitecustomize.py
```

with exactly these two lines:

```python
import truststore
truststore.inject_into_ssl()
```

> **Location matters:** it must go in `site-packages`, **not** the bare `.venv\Lib`
> folder. Only `site-packages` is guaranteed to be on `sys.path`, which is what
> makes Python auto-import `sitecustomize` at startup. A file in `.venv\Lib`
> alone is silently ignored.
>
> On macOS/Linux the path is `.venv/lib/pythonX.Y/site-packages/sitecustomize.py`
> instead.

### 3. Verify the fix

```powershell
.\.venv\Scripts\python.exe -c "import truststore, urllib.request; print(urllib.request.urlopen('https://pypi.org').status)"
```

Expect `200` and no traceback. If you still get an SSL error, see Troubleshooting.

## Why this is the right vehicle (a skill, not a committed file)

`.venv/` is git-ignored, so `sitecustomize.py` **cannot** be committed and shared
through the repo — each team member has their own local venv. This skill is how
the fix travels to the whole team: anyone who hits the error runs the skill and
reproduces the fix in their own environment.

## Troubleshooting

- **Still failing after both steps** — confirm `sitecustomize.py` is in
  `site-packages` (step 2's location note), and that you're running the venv's
  Python (`.venv\Scripts\python.exe`), not a global interpreter that doesn't see
  this venv.
- **`ModuleNotFoundError: No module named 'truststore'`** at startup — truststore
  didn't install into *this* venv. Re-run step 1 with the venv's own
  `python.exe -m pip`, not a global `pip`.
- **`pip` still fails even for the trusted-host install** — the corporate root CA
  can be exported from the Windows cert store and pointed at directly instead:
  `pip config set global.cert C:\path\to\etrog-root-ca.pem`. IT can supply the CA
  file.
- **Only `pip` needs fixing, not your app** — modern pip supports Etrog's store
  natively: `pip install --use-feature=truststore <pkg>` (pip ≥ 22.2). The
  `sitecustomize.py` approach above is broader because it covers all runtime
  HTTPS too (requests/httpx/urllib in the adapters).
