import json
import os
import sys

# Ensure the src directory is in the python path
sys.path.insert(0, os.path.abspath("services/status-board/src"))

from silvasonic.status_board.main import app


def generate_openapi() -> None:
    """Generate the OpenAPI schema for the Silvasonic Status Board service."""
    print("Generating OpenAPI schema...")
    openapi_schema = app.openapi()

    output_path = "docs/openapi.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(openapi_schema, f, indent=2)

    print(f"OpenAPI schema saved to {output_path}")


if __name__ == "__main__":
    generate_openapi()
