#!/usr/bin/env python3
"""Policy checks for infra/ that `terraform validate` cannot make (STEP-08 task 1).

    uv run python scripts/check_policy.py [--infra DIR]

Reads infra/policy/*.toml and every *.tf in each Terraform root under infra/, and fails on:
- a listed argument left out (explicit_args.toml `arguments`), or a missing ordering edge
  (`depends_on`);
- a location outside the allowed list for its service (locations.toml, D50, lesson L5);
- an editor job above the memory ceiling at its vCPU count, or with retries (limits.toml, L7, D52);
- a reference to a Cloud Run service's `uri` or `urls` (the URL comes from the project number, F61).

Prints one sorted line per violation. Exit 0 when clean, 1 on violations, 2 when the checker
cannot do its job (unreadable policy or Terraform).
"""

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import hcl2
from hcl2 import SerializationOptions
from lark.exceptions import UnexpectedInput

EXIT_CLEAN, EXIT_FOUND, EXIT_ERROR = 0, 1, 2
DEFAULT_INFRA = Path(__file__).resolve().parents[1] / "infra"
PARSE = SerializationOptions(with_comments=False, strip_string_quotes=True)

# Arguments that hold a location, by resource type; every other type uses LOCATION_ARGS.
LOCATION_ARGS = ("location", "region", "location_id")
LOCATION_PATHS = {"google_secret_manager_secret": ("replication.user_managed.replicas.location",)}
LOCAL_REF = re.compile(r"\$\{local\.(\w+)\}")
CASE_REF = re.compile(r"\$\{(upper|lower)\(local\.(\w+)\)\}")
SERVICE_URI = re.compile(r"google_cloud_run_v2_service\.\w+\.(?:uri|urls)\b")
MEMORY = re.compile(r"^(\d+)(Mi|Gi)$")
MIB_PER_GIB = 1024
JOB_TYPE = "google_cloud_run_v2_job"

Body = dict[str, object]


class PolicyError(Exception):
    """The checker could not read its inputs; exit 2 rather than pretend infra/ is clean."""


@dataclass(frozen=True)
class Resource:
    type: str
    name: str
    body: Body

    @property
    def address(self) -> str:
        return f"{self.type}.{self.name}"


@dataclass(frozen=True)
class Root:
    name: str
    resources: list[Resource]
    locals: Body


# ---------------------------------------------------------------- reading


def read_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PolicyError(f"cannot read {path.name}: {exc}") from exc


def parse_tf(path: Path) -> Body:
    try:
        with path.open(encoding="utf-8") as handle:
            data: Body = hcl2.load(handle, serialization_options=PARSE)
            return data
    except (OSError, UnexpectedInput) as exc:
        raise PolicyError(f"cannot parse {path}: {exc}") from exc


def dicts(value: object) -> list[Body]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def load_root(folder: Path) -> Root:
    resources: list[Resource] = []
    local_values: Body = {}
    for path in sorted(folder.glob("*.tf")):
        data = parse_tf(path)
        for block in dicts(data.get("resource")):
            for rtype, named in block.items():
                if isinstance(named, dict):
                    for name, body in named.items():
                        if isinstance(body, dict):
                            resources.append(Resource(rtype, name, body))
        for block in dicts(data.get("locals")):
            local_values.update(block)
    return Root(folder.name, resources, local_values)


def load_roots(infra: Path) -> list[Root]:
    folders = sorted(p for p in infra.iterdir() if p.is_dir() and any(p.glob("*.tf")))
    return [load_root(folder) for folder in folders]


# ---------------------------------------------------------------- navigating bodies


def children(body: Body, name: str) -> list[Body]:
    """Nested blocks called `name`, including the content of `dynamic "name"` blocks."""
    found = [b for b in dicts(body.get(name)) if b.get("__is_block__")]
    for dynamic in dicts(body.get("dynamic")):
        inner = dynamic.get(name)
        if isinstance(inner, dict):
            found += dicts(inner.get("content"))
    return found


def has_path(body: Body, path: str) -> bool:
    head, _, rest = path.partition(".")
    if not rest:
        return head in body or bool(children(body, head))
    return any(has_path(child, rest) for child in children(body, head))


def values_at(body: Body, path: str) -> list[object]:
    head, _, rest = path.partition(".")
    if not rest:
        return [body[head]] if head in body else []
    return [value for child in children(body, head) for value in values_at(child, rest)]


def resolve(value: object, local_values: Body, depth: int = 0) -> object:
    """A literal, or a `local.x` chain ending in one (upper()/lower() allowed); None otherwise."""
    if depth > len(local_values) or not isinstance(value, str) or "${" not in value:
        return value
    if match := LOCAL_REF.fullmatch(value):
        name = match.group(1)
        return (
            resolve(local_values[name], local_values, depth + 1) if name in local_values else None
        )
    if match := CASE_REF.fullmatch(value):
        inner = resolve(local_values.get(match.group(2)), local_values, depth + 1)
        if isinstance(inner, str) and "${" not in inner:
            return inner.upper() if match.group(1) == "upper" else inner.lower()
    return None


def other_resource(value: object) -> bool:
    """A reference to another resource's attribute: that resource is checked on its own."""
    return isinstance(value, str) and value.startswith("${google_")


# ---------------------------------------------------------------- rules


def explicit_args(root: Root, policy: dict[str, object]) -> list[str]:
    found = []
    for res in root.resources:
        rule = policy.get(res.type)
        if not isinstance(rule, dict):
            continue
        for path in strings(rule.get("arguments")):
            if not has_path(res.body, path):
                found.append(f"{res.address}: missing {path}")
        listed = set(strings(res.body.get("depends_on")))
        for needed in strings(rule.get("depends_on")):
            if "${" + needed + "}" not in listed:
                found.append(f"{res.address}: depends_on lacks {needed}")
    return found


def allowed_locations(policy: dict[str, object]) -> dict[str, list[str]]:
    allowed: dict[str, list[str]] = {}
    for service in policy.values():
        if isinstance(service, dict):
            for rtype in strings(service.get("resources")):
                allowed[rtype] = [a.lower() for a in strings(service.get("allowed"))]
    return allowed


def locations(root: Root, policy: dict[str, object]) -> list[str]:
    allowed_by_type = allowed_locations(policy)
    found = []
    for res in root.resources:
        allowed = allowed_by_type.get(res.type)
        if allowed is None:
            continue
        for path in LOCATION_PATHS.get(res.type, LOCATION_ARGS):
            for raw in values_at(res.body, path):
                if other_resource(raw):
                    continue
                value = resolve(raw, root.locals)
                if not isinstance(value, str):
                    found.append(f"{res.address}: cannot resolve {path} {raw!r}")
                elif value.lower() not in allowed:
                    found.append(
                        f"{res.address}: {path} {value} not allowed ({', '.join(allowed)})"
                    )
    return found


def mebibytes(memory: object) -> int | None:
    match = MEMORY.fullmatch(memory) if isinstance(memory, str) else None
    if match is None:
        return None
    amount = int(match.group(1))
    return amount * MIB_PER_GIB if match.group(2) == "Gi" else amount


def job_limits(root: Root, policy: dict[str, object]) -> list[str]:
    rule = policy.get("cloud_run_job")
    if not isinstance(rule, dict):
        raise PolicyError("limits.toml: [cloud_run_job] is missing")
    ceiling = mebibytes(rule.get("max_memory"))
    if ceiling is None:
        raise PolicyError("limits.toml: [cloud_run_job] max_memory must look like 16Gi")
    found = []
    for res in (r for r in root.resources if r.type == JOB_TYPE):
        for raw in values_at(res.body, "template.template.containers.resources.limits"):
            limits = raw if isinstance(raw, dict) else {}
            cpu = resolve(limits.get("cpu"), root.locals)
            memory = resolve(limits.get("memory"), root.locals)
            size = mebibytes(memory)
            if size is None:
                found.append(f"{res.address}: cannot resolve memory {limits.get('memory')!r}")
            elif str(cpu) == str(rule["cpu"]) and size > ceiling:
                found.append(
                    f"{res.address}: memory {memory} above {rule['max_memory']} at {cpu} vCPU"
                )
        for raw in values_at(res.body, "template.template.max_retries"):
            retries = resolve(raw, root.locals)
            if retries != rule["max_retries"]:
                found.append(f"{res.address}: max_retries {retries}, must be {rule['max_retries']}")
    return found


def service_uri(infra: Path, roots: list[Root]) -> list[str]:
    found = []
    for root in roots:
        for path in sorted((infra / root.name).glob("*.tf")):
            for match in SERVICE_URI.finditer(path.read_text(encoding="utf-8")):
                found.append(
                    f"{root.name}/{path.name}: {match.group(0)} used;"
                    " build the URL from the project number (F61)"
                )
    return found


def run(infra: Path) -> list[str]:
    policy_dir = infra / "policy"
    args = read_toml(policy_dir / "explicit_args.toml")
    allowed = read_toml(policy_dir / "locations.toml")
    limits = read_toml(policy_dir / "limits.toml")
    roots = load_roots(infra)
    if not roots:
        return ["infra: no Terraform root found"]
    found = service_uri(infra, roots)
    for root in roots:
        found += explicit_args(root, args) + locations(root, allowed) + job_limits(root, limits)
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Policy checks for infra/.")
    parser.add_argument("--infra", type=Path, default=DEFAULT_INFRA, help="the infra/ folder")
    options = parser.parse_args(argv)
    try:
        found = run(options.infra)
    except PolicyError as exc:
        sys.stderr.write(f"check_policy: {exc}\n")
        return EXIT_ERROR
    for line in found:
        sys.stdout.write(f"{line}\n")
    if found:
        return EXIT_FOUND
    sys.stdout.write("policy: 0 violations\n")
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
