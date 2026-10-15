"""SUPERSEDED AND DISABLED -- do not deploy this file.

This module used to hold a second copy of ``main()`` that Apply-ServerPatch.ps1
spliced into rig_gateway/server.py on a host without git. Two things were wrong
with that and both are the kind this project exists to prevent:

1. It was a *copy*. The deployed server and the source could disagree, and the
   divergence would be invisible -- the exact "config disagrees with the running
   server" trap the Skill warns about.
2. The copy it carried decided the HTTP bind with

       accepts_kwargs = "host" in run_params and "port" in run_params

   which misses ``**kwargs`` -- how every modern FastMCP declares run(). The
   deployed server would therefore fail to bind a TCP address at all.

Replaced by deploy/Deploy-RigGateway.ps1, which copies the whole package and
verifies each deployed file's SHA-256 against the source.

Running this file now does nothing but explain itself and exit non-zero, so an
older note that says "python patch_main.py" cannot re-break a host by accident.
"""
import sys

MESSAGE = __doc__.strip()

if __name__ == "__main__":
    print(MESSAGE, file=sys.stderr)
    print("\nNothing was changed. See deploy/Deploy-RigGateway.ps1.", file=sys.stderr)
    sys.exit(1)
