"""Publish only the app's static assets through Vercel's CDN."""
from pathlib import Path
from shutil import copytree


def main():
    root = Path(__file__).resolve().parent
    source = root / "frontend" / "static"
    destination = root / "public" / "static"
    copytree(source, destination, dirs_exist_ok=True)
    print("Prepared TalentSouk static assets for Vercel.")


if __name__ == "__main__":
    main()
