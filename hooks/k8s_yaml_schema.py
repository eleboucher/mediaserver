#!/usr/bin/env python3
import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jmespath  # type: ignore
from ruamel.yaml import YAML  # type: ignore

DIRECTIVE_RE = re.compile(r"^\s*#\s*yaml-language-server:\s*\$schema=(?P<url>\S+)\s*$")
DOC_MARKER_RE = re.compile(r"(?m)^---\s*$")


def _normalise_domain(domain: str) -> str:
    domain = domain.strip()
    domain = re.sub(r"^https?://", "", domain)
    domain = domain.rstrip("/")
    return domain


def _split_yaml_documents(text: str) -> List[Tuple[str, str]]:
    """
    Return a list of (marker, doc_text) where `marker` is '' for the first doc,
    or something like '---\\n' for subsequent docs (exactly as in source).
    We treat only column-0 '---' as a document marker (common for k8s manifests).
    """
    parts: List[Tuple[str, str]] = []
    cur_marker = ""
    start = 0

    for m in DOC_MARKER_RE.finditer(text):
        marker_start = m.start()
        marker_end = m.end()

        doc_text = text[start:marker_start]

        line_end = marker_end
        if line_end < len(text) and text[line_end] == "\n":
            line_end += 1
        marker_text = text[marker_start:line_end]

        parts.append((cur_marker, doc_text))
        cur_marker = marker_text
        start = line_end

    parts.append((cur_marker, text[start:]))
    return parts


def _is_k8s_resource(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    return bool(obj.get("apiVersion")) and bool(obj.get("kind"))


def _is_core_api(api_version_full: str) -> bool:
    return "/" not in api_version_full.strip()


def _api_group_and_version(api_version_full: str, core_group: str) -> Tuple[str, str]:
    if "/" in api_version_full:
        group, version = api_version_full.split("/", 1)
        return group, version
    return core_group, api_version_full


def _render_template(template: str, vars: Dict[str, str]) -> str:
    try:
        return template.format(**vars)
    except KeyError as e:
        raise ValueError(f"Template references missing key: {e}") from e


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    yaml = YAML(typ="safe")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.load(f)  # may be None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must be a mapping/object: {path}")
    return data


def _match_rule(
    match: Dict[str, Any],
    obj: Dict[str, Any],
    file_posix: str,
    api_group: str,
    api_version: str,
    api_version_full: str,
) -> bool:
    def _match_scalar(field_val: str, cond: Any) -> bool:
        if cond is None:
            return True
        if isinstance(cond, list):
            return field_val in [str(x) for x in cond]
        return field_val == str(cond)

    if "file_regex" in match:
        pat = str(match["file_regex"])
        if re.search(pat, file_posix) is None:
            return False

    kind = str(obj.get("kind", ""))
    if not _match_scalar(kind, match.get("kind")):
        return False

    if not _match_scalar(api_group, match.get("apiGroup")):
        return False

    if not _match_scalar(api_version, match.get("apiVersion")):
        return False

    if not _match_scalar(api_version_full, match.get("apiVersionFull")):
        return False

    if "jmespath" in match:
        expr = str(match["jmespath"])
        val = jmespath.search(expr, obj)

        if "exists" in match:
            want = bool(match["exists"])
            if want != (val is not None):
                return False

        if "equals" in match:
            if val != match["equals"]:
                return False

        if "one_of" in match:
            options = match["one_of"]
            if not isinstance(options, list):
                return False
            if val not in options:
                return False

        if "match_regex" in match:
            pat = str(match["match_regex"])
            if val is None:
                return False
            if re.search(pat, str(val)) is None:
                return False

    return True


def _schema_for_resource(
    obj: Dict[str, Any],
    file_posix: str,
    domain: str,
    core_group: str,
    schema_template: str,
    overrides: List[Dict[str, Any]],
) -> str:
    api_version_full = str(obj.get("apiVersion", ""))
    kind = str(obj.get("kind", ""))
    api_group, api_version = _api_group_and_version(api_version_full, core_group)
    kind_lc = kind.lower()

    vars = {
        "domain": domain,
        "apiGroup": api_group,
        "apiVersion": api_version,
        "apiVersionFull": api_version_full,
        "kind": kind,
        "kind_lower": kind_lc,
        "kind_lowercase": kind_lc,
        "file": file_posix,
    }

    for rule in overrides:
        match = rule.get("match") or rule.get("when") or {}
        if not isinstance(match, dict):
            continue

        if _match_rule(
            match, obj, file_posix, api_group, api_version, api_version_full
        ):
            schema = str(rule.get("schema", "")).strip()
            if not schema:
                continue
            if (
                "{domain}" in schema
                or "{apiGroup}" in schema
                or "{kind" in schema
                or "{apiVersion" in schema
            ):
                return _render_template(schema, vars)
            return schema

    return _render_template(schema_template, vars)


def _ensure_directive(doc_text: str, expected_url: str) -> Tuple[str, bool]:
    """
    Ensure a yaml-language-server directive exists for this document and matches expected_url.
    Return (new_doc_text, changed).
    Directive is placed as the first non-blank line in the doc.
    If a directive exists in the leading comment block, it is updated.
    """
    lines = doc_text.splitlines(keepends=True)

    def _first_content_index() -> int:
        i = 0
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        return i

    # Scan until first non-blank, non-comment (i.e. first content line).
    for i, line in enumerate(lines):
        if line.strip() == "":
            continue
        if line.lstrip().startswith("#"):
            m = DIRECTIVE_RE.match(line)
            if m:
                current = m.group("url")
                if current == expected_url:
                    return doc_text, False
                nl = "\n" if line.endswith("\n") else ""
                lines[i] = f"# yaml-language-server: $schema={expected_url}{nl}"
                return "".join(lines), True
            continue
        break

    # No directive found: insert at start (after leading blanks).
    insert_at = _first_content_index()
    lines.insert(insert_at, f"# yaml-language-server: $schema={expected_url}\n")
    return "".join(lines), True


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--domain",
        default=None,
        help="Schema host (or full base without path). Can also be set in config or env YAML_SCHEMA_DOMAIN/DOMAIN.",
    )
    ap.add_argument(
        "--config", default=".k8s-schema-hook.yaml", help="Override config YAML path."
    )
    ap.add_argument(
        "--core-group",
        default=None,
        help="apiGroup name used for core resources (apiVersion without '/'). Default: 'core' (or config core_group).",
    )
    ap.add_argument(
        "--schema-template",
        default=None,
        help="Template for default schema URL (or from config).",
    )

    # New: include/exclude core resources (default false)
    ap.add_argument(
        "--include-core",
        dest="include_core",
        action="store_true",
        help="Also add/update schemas for core API resources (apiVersion like 'v1').",
    )
    ap.add_argument(
        "--no-include-core",
        dest="include_core",
        action="store_false",
        help="Do not add/update schemas for core API resources.",
    )
    ap.set_defaults(include_core=None)

    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)

    cfg_path = Path(args.config)
    cfg = _load_yaml_file(cfg_path)

    domain = (
        args.domain
        or cfg.get("domain")
        or os.environ.get("YAML_SCHEMA_DOMAIN")
        or os.environ.get("DOMAIN")
    )
    if not domain:
        print(
            "k8s-yaml-schema: missing domain (use --domain, config 'domain:', or env YAML_SCHEMA_DOMAIN/DOMAIN)",
            file=sys.stderr,
        )
        return 2
    domain = _normalise_domain(str(domain))

    core_group = str(args.core_group or cfg.get("core_group") or "core")

    schema_template = str(
        args.schema_template
        or cfg.get("schema_template")
        or "https://{domain}/{apiGroup}/{kind_lowercase}_{apiVersion}.json"
    )

    # New: default false unless explicitly enabled
    include_core_cfg = cfg.get("include_core", False)
    include_core = (
        bool(include_core_cfg) if args.include_core is None else bool(args.include_core)
    )

    overrides = cfg.get("overrides") or []
    if not isinstance(overrides, list):
        print("k8s-yaml-schema: config 'overrides' must be a list", file=sys.stderr)
        return 2

    yaml = YAML(typ="safe")

    any_changed = False
    had_error = False

    for file_str in args.files:
        path = Path(file_str)
        if not path.exists():
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"k8s-yaml-schema: failed reading {file_str}: {e}", file=sys.stderr)
            had_error = True
            continue

        parts = _split_yaml_documents(text)
        new_parts: List[Tuple[str, str]] = []

        file_posix = file_str.replace(os.sep, "/")

        file_changed = False
        doc_idx = 0

        for marker, doc_text in parts:
            doc_idx += 1

            try:
                obj = yaml.load(doc_text)
            except Exception as e:
                if doc_text.strip() != "":
                    print(
                        f"k8s-yaml-schema: YAML parse error in {file_str} (document #{doc_idx}): {e}",
                        file=sys.stderr,
                    )
                    had_error = True
                new_parts.append((marker, doc_text))
                continue

            if obj is None or not _is_k8s_resource(obj):
                new_parts.append((marker, doc_text))
                continue

            api_version_full = str(obj.get("apiVersion", "")).strip()

            # New: skip core resources unless include_core is enabled
            if _is_core_api(api_version_full) and not include_core:
                new_parts.append((marker, doc_text))
                continue

            expected = _schema_for_resource(
                obj=obj,
                file_posix=file_posix,
                domain=domain,
                core_group=core_group,
                schema_template=schema_template,
                overrides=overrides,
            )

            new_doc_text, changed = _ensure_directive(doc_text, expected)
            if changed:
                file_changed = True
            new_parts.append((marker, new_doc_text))

        if file_changed:
            out = "".join([m + d for (m, d) in new_parts])
            if out != text:
                path.write_text(out, encoding="utf-8")
                print(f"k8s-yaml-schema: updated {file_str}", file=sys.stderr)
                any_changed = True

    if had_error:
        return 2
    if any_changed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
