#!/usr/bin/env python3

"""Generate a Markdown inventory of installed Python dependencies."""

import argparse
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path


def escape_markdown(value):
    return " ".join(str(value).split()).replace("|", r"\|")


def project_url(meta, name):
    urls = {}

    for entry in meta.get_all("Project-URL") or []:
        label, separator, url = entry.partition(",")

        if separator:
            urls[label.strip().casefold()] = url.strip()

    for label in (
        "repository",
        "source",
        "source code",
        "homepage",
        "home page",
        "github",
        "documentation",
    ):
        if urls.get(label):
            return urls[label]

    homepage = meta.get("Home-page")

    if homepage and homepage.startswith(("https://", "http://")):
        return homepage

    return f"https://pypi.org/project/{name}/"


def license_information(meta):
    expression = meta.get("License-Expression")

    if expression and expression.strip():
        return expression.strip(), "License-Expression"

    classifiers = [
        value.removeprefix("License :: ").strip()
        for value in meta.get_all("Classifier") or []
        if value.startswith("License :: ")
    ]

    license_text = meta.get("License", "").strip()

    if license_text:
        if len(license_text) <= 160 and "\n" not in license_text:
            if license_text.casefold() not in ("unknown", "none"):
                return license_text, "License metadata"

    if classifiers:
        return "; ".join(classifiers), "Classifier"

    if license_text:
        return (
            "See installed license text",
            "Full license text or ambiguous metadata",
        )

    return "REVIEW REQUIRED", "No usable license declaration"


def collect_dependencies():
    rows = []

    for distribution in metadata.distributions():
        meta = distribution.metadata
        name = meta.get("Name")

        if not name:
            continue

        license_name, license_source = license_information(meta)

        rows.append({
            "name": name,
            "version": distribution.version,
            "url": project_url(meta, name),
            "license": license_name,
            "license_source": license_source,
        })

    return sorted(rows, key=lambda row: row["name"].casefold())


def make_report(environment, rows):
    generated = datetime.now(timezone.utc).isoformat()

    lines = [
        f"# Python dependency inventory — {environment}",
        "",
        f"- Generated: {generated}",
        f"- Python version: {sys.version.split()[0]}",
        f"- Installed distributions: {len(rows)}",
        "",
        "This inventory reflects installed package metadata.",
        "License declarations have not been independently verified.",
        "Installation does not imply direct use by HeHawk.",
        "Model weights and external executables require separate review.",
        "",
        "| Package | Version | Project URL | Declared license | Metadata source |",
        "|---|---|---|---|---|",
    ]

    for row in rows:
        fields = [
            row["name"],
            row["version"],
            row["url"],
            row["license"],
            row["license_source"],
        ]

        lines.append(
            "| " + " | ".join(
                escape_markdown(value) for value in fields
            ) + " |"
        )

    review = [
        row for row in rows
        if row["license_source"] in (
            "No usable license declaration",
            "Full license text or ambiguous metadata",
        )
    ]

    lines.extend([
        "",
        "## Metadata requiring additional review",
        "",
    ])

    if review:
        for row in review:
            lines.append(
                f"- {row['name']} {row['version']}: "
                f"{row['license_source']}"
            )
    else:
        lines.append("No missing or ambiguous declarations detected.")

    lines.extend([
        "",
        "All license declarations remain subject to upstream verification.",
    ])

    return "\n".join(lines) + "\n", len(review)


def main():
    parser = argparse.ArgumentParser(
        description="Generate an installed dependency inventory."
    )

    parser.add_argument("--environment", required=True)
    parser.add_argument("--output", required=True, type=Path)

    args = parser.parse_args()

    rows = collect_dependencies()
    report, review_count = make_report(args.environment, rows)

    try:
        with args.output.open("x", encoding="utf-8") as output:
            output.write(report)
    except FileExistsError:
        parser.exit(
            1,
            f"ERROR: Output already exists: {args.output}\n"
        )

    print(f"Environment: {args.environment}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Installed distributions: {len(rows)}")
    print(f"Metadata requiring review: {review_count}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
