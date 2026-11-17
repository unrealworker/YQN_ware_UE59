"""Check the actual UAT staging manifest includes every runtime roof scan material.

Native constructor soft paths are not enough to guarantee cook discovery. Run
this after cooking/staging, before accepting or distributing a warehouse build.
"""
import argparse
import json
from pathlib import Path
import sys


ROOF_DIRECTORIES = (
    "GHSZcoolSmartFactory/Roof/ScanReveal",
    "MPRWarehouse/Roof/ScanReveal",
)


def verify(project: Path, manifest: Path) -> dict:
    text = manifest.read_text(encoding="utf-8-sig").replace("\\", "/").casefold()
    expected = []
    for directory in ROOF_DIRECTORIES:
        files = sorted((project / "Content" / directory).glob("M_Scan_*.uasset"))
        if not files:
            raise RuntimeError(f"Roof material source directory is empty: {directory}")
        expected.extend("Content/" + directory + "/" + path.name for path in files)
    missing = [path for path in expected if path.casefold() not in text]
    return {
        "pass": not missing,
        "manifest": str(manifest.resolve()),
        "expectedCount": len(expected),
        "presentCount": len(expected) - len(missing),
        "expected": expected,
        "missing": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="UAT FinalCopyWasm_UFSFiles.txt or equivalent platform manifest")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = verify(args.project, args.manifest)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
