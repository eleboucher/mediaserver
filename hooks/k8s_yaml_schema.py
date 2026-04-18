#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

import jmespath  # type: ignore[import-untyped]
from ruamel.yaml import YAML  # type: ignore[import-untyped]

DIRECTIVE_RE = re.compile(r"^\s*#\s*yaml-language-server:\s*\$schema=(?P<url>\S+)\s*$")
DOC_MARKER_RE = re.compile(r"(?m)^---\s*$")
DEFAULT_SCHEMA_TEMPLATE = (
    "https://{domain}/{apiGroup}/{kind_lowercase}_{apiVersion}.json"
)


def _normalise_domain(domain: str) -> str:
    return re.sub(r"^https?://", "", domain.strip()).rstrip("/")


def _split_yaml_documents(text: str) -> list[tuple[str, str]]:
    """Split `text` into (marker, body) pairs around column-0 `---` separators.

    The marker is '' for the first doc, and the literal `---\\n` (or variant)
    for subsequent docs so the file round-trips byte-for-byte.
    """
    parts: list[tuple[str, str]] = []
    cur_marker = ""
    start = 0

    for m in DOC_MARKER_RE.finditer(text):
        line_end = m.end() + 1 if m.end() < len(text) and text[m.end()] == "\n" else m.end()
        parts.append((cur_marker, text[start : m.start()]))
        cur_marker = text[m.start() : line_end]
        start = line_end

    parts.append((cur_marker, text[start:]))
    return parts


def _is_k8s_resource(obj: Any) -> bool:
    return isinstance(obj, dict) and bool(obj.get("apiVersion")) and bool(obj.get("kind"))


def _is_core_api(api_version_full: str) -> bool:
    return "/" not in api_version_full.strip()


def _api_group_and_version(api_version_full: str, core_group: str) -> tuple[str, str]:
    if "/" in api_version_full:
        group, version = api_version_full.split("/", 1)
        return group, version
    return core_group, api_version_full


def _render_template(template: str, values: dict[str, str]) -> str:
    try:
        return template.format(**values)
    except KeyError as e:
        raise ValueError(f"Template references missing key: {e}") from e


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must be a mapping/object: {path}")
    return data


def _load_sidecar_ocirepos(
    dir_path: Path, cache: dict[Path, dict[str, str]]
) -> dict[str, str]:
    """Return `{metadata.name: spec.url}` for OCIRepository docs alongside the HelmRelease."""
    if dir_path in cache:
        return cache[dir_path]

    result: dict[str, str] = {}
    yaml = YAML(typ="safe")
    for fname in ("ocirepository.yaml", "ocirepository.yml"):
        candidate = dir_path / fname
        if not candidate.exists():
            continue
        try:
            with candidate.open("r", encoding="utf-8") as f:
                docs = list(yaml.load_all(f))
        except Exception:
            continue
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("kind") != "OCIRepository":
                continue
            name = str((doc.get("metadata") or {}).get("name") or "")
            url = str((doc.get("spec") or {}).get("url") or "")
            if name and url:
                result[name] = url

    cache[dir_path] = result
    return result


def _chart_ref_oci_url(
    obj: dict[str, Any],
    file_posix: str,
    cache: dict[Path, dict[str, str]],
) -> str | None:
    chart_ref = (obj.get("spec") or {}).get("chartRef") or {}
    if not isinstance(chart_ref, dict) or chart_ref.get("kind") != "OCIRepository":
        return None
    name = str(chart_ref.get("name") or "")
    if not name:
        return None
    return _load_sidecar_ocirepos(Path(file_posix).parent, cache).get(name)


def _match_value(val: Any, cond: Any) -> bool:
    """Match `val` against `cond`.

    `cond` may be `None` (match anything), a scalar (equality), a list (membership),
    or a dict with any of `{exists, equals, one_of, match_regex}`.
    """
    if cond is None:
        return True
    if isinstance(cond, dict):
        if "exists" in cond and bool(cond["exists"]) != (val is not None):
            return False
        if "equals" in cond and val != cond["equals"]:
            return False
        if "one_of" in cond and val not in (cond["one_of"] or []):
            return False
        if "match_regex" in cond:
            if val is None or re.search(str(cond["match_regex"]), str(val)) is None:
                return False
        return True
    if isinstance(cond, list):
        return str(val or "") in [str(x) for x in cond]
    return str(val or "") == str(cond)


def _match_rule(
    match: dict[str, Any],
    obj: dict[str, Any],
    file_posix: str,
    api_group: str,
    api_version: str,
    api_version_full: str,
    sidecar_cache: dict[Path, dict[str, str]],
) -> bool:
    if "file_regex" in match and re.search(str(match["file_regex"]), file_posix) is None:
        return False

    if not _match_value(obj.get("kind", ""), match.get("kind")):
        return False
    if not _match_value(api_group, match.get("apiGroup")):
        return False
    if not _match_value(api_version, match.get("apiVersion")):
        return False
    if not _match_value(api_version_full, match.get("apiVersionFull")):
        return False

    if "chartRefOciUrl" in match:
        url = _chart_ref_oci_url(obj, file_posix, sidecar_cache)
        if not _match_value(url, match["chartRefOciUrl"]):
            return False

    if "jmespath" in match:
        val = jmespath.search(str(match["jmespath"]), obj)
        inline = {k: match[k] for k in ("exists", "equals", "one_of", "match_regex") if k in match}
        if inline and not _match_value(val, inline):
            return False

    return True


def _schema_for_resource(
    obj: dict[str, Any],
    file_posix: str,
    domain: str,
    core_group: str,
    schema_template: str,
    overrides: list[dict[str, Any]],
    sidecar_cache: dict[Path, dict[str, str]],
) -> str:
    api_version_full = str(obj.get("apiVersion", ""))
    kind = str(obj.get("kind", ""))
    api_group, api_version = _api_group_and_version(api_version_full, core_group)

    template_vars = {
        "domain": domain,
        "apiGroup": api_group,
        "apiVersion": api_version,
        "apiVersionFull": api_version_full,
        "kind": kind,
        "kind_lower": kind.lower(),
        "kind_lowercase": kind.lower(),
        "file": file_posix,
    }

    for rule in overrides:
        match = rule.get("match") or rule.get("when") or {}
        if not isinstance(match, dict):
            continue
        if not _match_rule(
            match, obj, file_posix, api_group, api_version, api_version_full, sidecar_cache
        ):
            continue
        schema = str(rule.get("schema", "")).strip()
        if not schema:
            continue
        return _render_template(schema, template_vars) if "{" in schema else schema

    return _render_template(schema_template, template_vars)


def _ensure_directive(doc_text: str, expected_url: str) -> tuple[str, bool]:
    """Insert or update the `yaml-language-server` schema directive at the top of `doc_text`.

    The directive is placed as the first non-blank line. An existing directive in the
    leading comment block is rewritten in place. Returns (new_text, changed).
    """
    lines = doc_text.splitlines(keepends=True)

    for i, line in enumerate(lines):
        if line.strip() == "":
            continue
        if not line.lstrip().startswith("#"):
            break
        m = DIRECTIVE_RE.match(line)
        if m is None:
            continue
        if m.group("url") == expected_url:
            return doc_text, False
        nl = "\n" if line.endswith("\n") else ""
        lines[i] = f"# yaml-language-server: $schema={expected_url}{nl}"
        return "".join(lines), True

    insert_at = next((i for i, line in enumerate(lines) if line.strip() != ""), len(lines))
    lines.insert(insert_at, f"# yaml-language-server: $schema={expected_url}\n")
    return "".join(lines), True


def _resolve_domain(args: argparse.Namespace, cfg: dict[str, Any]) -> str | None:
    return (
        args.domain
        or cfg.get("domain")
        or os.environ.get("YAML_SCHEMA_DOMAIN")
        or os.environ.get("DOMAIN")
    )


def _build_parser() -> argparse.ArgumentParser:
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
    return ap


def _process_file(
    path: Path,
    *,
    domain: str,
    core_group: str,
    schema_template: str,
    overrides: list[dict[str, Any]],
    include_core: bool,
    sidecar_cache: dict[Path, dict[str, str]],
) -> tuple[bool, bool]:
    """Update `path` in place. Returns (changed, had_error)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"k8s-yaml-schema: failed reading {path}: {e}", file=sys.stderr)
        return False, True

    yaml = YAML(typ="safe")
    file_posix = str(path).replace(os.sep, "/")
    new_parts: list[tuple[str, str]] = []
    changed = False
    had_error = False

    for doc_idx, (marker, doc_text) in enumerate(_split_yaml_documents(text), start=1):
        try:
            obj = yaml.load(doc_text)
        except Exception as e:
            if doc_text.strip():
                print(
                    f"k8s-yaml-schema: YAML parse error in {path} (document #{doc_idx}): {e}",
                    file=sys.stderr,
                )
                had_error = True
            new_parts.append((marker, doc_text))
            continue

        if not _is_k8s_resource(obj):
            new_parts.append((marker, doc_text))
            continue

        api_version_full = str(obj.get("apiVersion", "")).strip()
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
            sidecar_cache=sidecar_cache,
        )
        new_doc_text, doc_changed = _ensure_directive(doc_text, expected)
        changed = changed or doc_changed
        new_parts.append((marker, new_doc_text))

    if changed:
        out = "".join(m + d for m, d in new_parts)
        if out != text:
            path.write_text(out, encoding="utf-8")
            print(f"k8s-yaml-schema: updated {path}", file=sys.stderr)
            return True, had_error

    return False, had_error


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cfg = _load_yaml_file(Path(args.config))

    domain = _resolve_domain(args, cfg)
    if not domain:
        print(
            "k8s-yaml-schema: missing domain (use --domain, config 'domain:', or env YAML_SCHEMA_DOMAIN/DOMAIN)",
            file=sys.stderr,
        )
        return 2

    core_group = str(args.core_group or cfg.get("core_group") or "core")
    schema_template = str(
        args.schema_template or cfg.get("schema_template") or DEFAULT_SCHEMA_TEMPLATE
    )
    include_core = (
        bool(cfg.get("include_core", False))
        if args.include_core is None
        else bool(args.include_core)
    )

    overrides = cfg.get("overrides") or []
    if not isinstance(overrides, list):
        print("k8s-yaml-schema: config 'overrides' must be a list", file=sys.stderr)
        return 2

    sidecar_cache: dict[Path, dict[str, str]] = {}
    any_changed = False
    had_error = False

    for file_str in args.files:
        path = Path(file_str)
        if not path.exists():
            continue
        changed, file_error = _process_file(
            path,
            domain=_normalise_domain(str(domain)),
            core_group=core_group,
            schema_template=schema_template,
            overrides=overrides,
            include_core=include_core,
            sidecar_cache=sidecar_cache,
        )
        any_changed = any_changed or changed
        had_error = had_error or file_error

    if had_error:
        return 2
    return 1 if any_changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
