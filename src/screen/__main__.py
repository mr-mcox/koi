"""Command-line interface entry point."""

from screen.intake.cli import intake


def main() -> int:
    """Entry point used by `python -m screen <url>`.

    Click manages --help, stdout/stderr, and exit codes via
    `standalone_mode=True` (the default). On a non-zero exit, click
    raises SystemExit, which Python's runpy handles correctly.
    """
    intake.main(standalone_mode=True, max_content_width=120)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
