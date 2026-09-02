# Deprecated: MCP stdio runner is deprecated for desktop build.
import sys

if __name__ == "__main__":
    print("MCP stdio mode is deprecated and unsupported in the desktop distribution.", file=sys.stderr)
    sys.exit(1)
