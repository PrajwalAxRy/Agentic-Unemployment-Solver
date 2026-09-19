"""Allow ``python -m job_finder`` to run the command-line interface."""

from job_finder.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
