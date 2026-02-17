#!/usr/bin/env python3
"""Build all Silvasonic container images via compose build.

Each Python service has a self-contained multi-stage Dockerfile,
so no manual build ordering is needed.
"""

from common import print_header, print_step, print_success
from compose import compose


def main() -> None:
    """Build all images via compose."""
    print_header("Building Silvasonic Container Images")
    print_step("Building all compose services...")
    compose("build")
    print_success("All images built! 🎉")


if __name__ == "__main__":
    main()
