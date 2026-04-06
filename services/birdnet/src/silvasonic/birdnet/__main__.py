"""Entrypoint for the BirdNET service container."""

from silvasonic.birdnet.service import BirdNETService


def main() -> None:
    """Instantiate and start the BirdNET service."""
    svc = BirdNETService()
    svc.start()


if __name__ == "__main__":
    main()
