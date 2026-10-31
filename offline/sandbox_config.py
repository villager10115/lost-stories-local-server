"""Generate a network-disabled Windows Sandbox configuration; never launches it."""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


def configuration(staging):
    staging = Path(staging).resolve(strict=True)
    if not staging.is_dir() or staging == Path(staging.anchor):
        raise ValueError("Select a dedicated staging directory, not a drive root")
    root = ET.Element("Configuration")
    for name, value in (
        ("Networking", "Disable"), ("ClipboardRedirection", "Disable"),
        ("PrinterRedirection", "Disable"), ("AudioInput", "Disable"),
        ("VideoInput", "Disable"), ("vGPU", "Disable"),
    ):
        ET.SubElement(root, name).text = value
    folders = ET.SubElement(root, "MappedFolders")
    folder = ET.SubElement(folders, "MappedFolder")
    ET.SubElement(folder, "HostFolder").text = str(staging)
    ET.SubElement(folder, "SandboxFolder").text = r"C:\OfflineInput"
    ET.SubElement(folder, "ReadOnly").text = "true"
    # No logon command: preparing a configuration must not execute game code.
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staging", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".wsb":
        parser.error("Output must use the .wsb extension")
    content = configuration(args.staging)
    with args.output.open("x", encoding="utf-8") as target:
        target.write(content)
    print("Configuration only; requires Windows Sandbox. No application launched.")


if __name__ == "__main__":
    main()
