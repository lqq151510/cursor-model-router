#!/usr/bin/env python3
"""Build a minimal VSIX for the dependency-free Cursor extension."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "cursor-extension"
PACKAGE = json.loads((EXTENSION / "package.json").read_text(encoding="utf-8"))
EXTENSION_ID = f"{PACKAGE['publisher']}.{PACKAGE['name']}"
VERSION = PACKAGE["version"]
OUTPUT = ROOT / f"{EXTENSION_ID}-{VERSION}.vsix"

manifest = f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{PACKAGE['name']}" Version="{VERSION}" Publisher="{PACKAGE['publisher']}" />
    <DisplayName>{PACKAGE['displayName']}</DisplayName>
    <Description xml:space="preserve">{PACKAGE['description']}</Description>
    <Tags>cursor,model,router,context,reasoning</Tags>
    <Categories>Other</Categories>
    <Properties />
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code" />
  </Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" />
  </Assets>
</PackageManifest>'''
content_types = '''<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="vsixmanifest" ContentType="text/xml" />
  <Default Extension="json" ContentType="application/json" />
  <Default Extension="js" ContentType="application/javascript" />
  <Override PartName="/extension.vsixmanifest" ContentType="text/xml" />
</Types>'''

with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
    archive.writestr("extension.vsixmanifest", manifest)
    archive.writestr("[Content_Types].xml", content_types)
    for relative in ("package.json", "extension.js"):
        archive.write(EXTENSION / relative, f"extension/{relative}")

print(OUTPUT)
