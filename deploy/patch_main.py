def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--enable-tier2", action="store_true",
                    help="screenshot and file mutation tools")
    ap.add_argument("--enable-tier3", action="store_true",
                    help="command execution and keystroke injection (needs RIG_ALLOW_TIER3=1 too)")
    args = ap.parse_args()

    if not SANDBOX_ROOT:
        print("WARNING: RIG_SANDBOX_ROOT is unset. Reads work; every write will be refused.",
              file=sys.stderr)

    build(args.enable_tier2, args.enable_tier3)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # FastMCP's API for binding host/port differs across versions, and the
        # Settings model rejects unknown fields with ValueError. Try the
        # documented run() arguments first, then fall back to setting the
        # attributes directly.
        import inspect

        run_params = inspect.signature(mcp.run).parameters
        accepts_kwargs = "host" in run_params and "port" in run_params
        if accepts_kwargs:
            mcp.run(transport="streamable-http", host=args.host, port=args.port)
        else:
            # If the attributes cannot be set, do NOT fall through to run():
            # it would silently bind 127.0.0.1 instead of the requested address,
            # which looks like a network fault and is not. Fail loudly instead.
            failures = []
            for attr, value in (("host", args.host), ("port", args.port)):
                try:
                    setattr(mcp.settings, attr, value)
                except Exception as exc:  # noqa: BLE001
                    failures.append("settings.%s = %r: %s" % (attr, value, exc))
            if failures:
                raise SystemExit(
                    "Cannot bind the requested address with this FastMCP version:\n  "
                    + "\n  ".join(failures)
                    + "\nPass --host/--port to run(), or pin a FastMCP version that "
                      "supports them.")
            mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
