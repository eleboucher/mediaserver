#!/usr/bin/env python3
import sys

# The exact schema line required
REQUIRED_SCHEMA = "# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s-labs/helm-charts/app-template-4.5.0/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json"


def main():
    files_modified = False

    for filename in sys.argv[1:]:
        try:
            with open(filename, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except IOError:
            continue

        # Prepare to write back if needed
        needs_fix = False

        # Handle empty files
        if not lines:
            return
        else:
            first_line = lines[0].strip()
            if (
                "app-template" not in "".join(lines)
                or "bjw-s" not in "".join(lines)
                or "HelmRelease" not in "".join(lines)
            ):
                continue
            # Check if the first line matches exactly
            if first_line != REQUIRED_SCHEMA:
                needs_fix = True
                print(f"Fixing schema in: {filename}")

                # If the first line is already a schema comment (but wrong one), replace it
                if first_line.startswith("# yaml-language-server:"):
                    lines[0] = REQUIRED_SCHEMA + "\n"
                else:
                    # Otherwise, prepend the schema and a blank line
                    lines.insert(0, REQUIRED_SCHEMA + "\n")
                    # Optional: Add a blank line if the next line isn't blank/separator
                    if (
                        len(lines) > 1
                        and lines[1].strip() != ""
                        and lines[1].strip() != "---"
                    ):
                        lines.insert(1, "\n")

        if needs_fix:
            with open(filename, "w", encoding="utf-8") as f:
                f.writelines(lines)
            files_modified = True

    if files_modified:
        sys.exit(1)


if __name__ == "__main__":
    main()
