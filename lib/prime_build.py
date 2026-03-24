#!/usr/bin/env python3
"""prime-build — generates a context file with all project code, line-numbered.
Called by the prime shell wrapper. Output used with --append-system-prompt-file.

The 1M context window makes this possible: preload your entire codebase
so Claude starts every session with full awareness. Zero Read calls needed."""

import json, os, sys, re, glob as globmod

VERSION = "1.0.0"
HOME = os.path.expanduser("~")
REGISTRY = os.path.join(HOME, ".prime", "projects.json")
PRIMERC_NAMES = [".primerc", "prime.json", ".prime.json"]

# Token limit — Prime is built for the 1M context window
TOKEN_LIMIT = 1_000_000


def read_file_numbered(filepath, label=None):
    """Read a file and return it with line numbers for citation."""
    if label is None:
        label = filepath
    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"### {label}\n[Error: {e}]\n"
    numbered = [f"{i:5d}\t{line.rstrip()}" for i, line in enumerate(lines, 1)]
    return f"### {label} ({len(lines)} lines)\n```\n" + "\n".join(numbered) + "\n```\n"


def find_primerc(start_dir=None):
    """Walk up from start_dir looking for .primerc / prime.json."""
    d = os.path.abspath(start_dir or os.getcwd())
    while True:
        for name in PRIMERC_NAMES:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p, d
        parent = os.path.dirname(d)
        if parent == d:
            return None, None
        d = parent


def resolve_globs(patterns, base_dir):
    """Expand glob patterns relative to base_dir. Plain paths pass through."""
    files = []
    empty_globs = []
    for pat in patterns:
        full = os.path.join(base_dir, pat)
        if any(c in pat for c in "*?["):
            matches = sorted(globmod.glob(full, recursive=True))
            matched = [m for m in matches if os.path.isfile(m)]
            if not matched:
                empty_globs.append(pat)
            files.extend(matched)
        elif os.path.isfile(full):
            files.append(full)
    for pat in empty_globs:
        print(f"  warning: glob matched 0 files: {pat}")
    return files


def load_from_registry(query):
    """Find a project in the central registry by fuzzy name match."""
    if not os.path.isfile(REGISTRY):
        return None, None
    with open(REGISTRY) as f:
        projects = json.load(f)
    q = query.lower().replace("-", " ")
    for name, config in projects.items():
        if q in name.lower().replace("-", " "):
            return name, config
    return None, None


def load_from_primerc(rc_path, project_dir):
    """Load project config from a local .primerc file."""
    with open(rc_path) as f:
        config = json.load(f)
    config.setdefault("path", project_dir)
    name = config.get("name", os.path.basename(project_dir))
    return name, config


def build_context(name, config):
    """Build the context text from a project config. Returns (content, stats)."""
    project_path = os.path.expanduser(config["path"])
    key_files = config.get("key_files", [])
    extra_files = config.get("extra_files", [])
    skill_file = config.get("skill_file", "")
    max_tokens = config.get("max_tokens", 0)

    blocks = []
    file_labels = []
    total_files = 0
    missing = []

    # 1. Skill file (workflow instructions, loaded first for context)
    if skill_file:
        sf = os.path.expanduser(skill_file)
        if os.path.isfile(sf):
            blocks.append(read_file_numbered(sf, f"SKILL: {os.path.basename(os.path.dirname(sf))}/{os.path.basename(sf)}"))
            file_labels.append(f"  - [SKILL] {skill_file}")
            total_files += 1
            print(f"  skill: {sf}")
        else:
            print(f"  skill missing: {sf}")

    # 2. Key files (relative to project, supports globs)
    resolved = resolve_globs(key_files, project_path)
    for full in resolved:
        rel = os.path.relpath(full, project_path)
        blocks.append(read_file_numbered(full, rel))
        file_labels.append(f"  - {rel}")
        total_files += 1
    not_found = [p for p in key_files if not any(c in p for c in "*?[") and not os.path.isfile(os.path.join(project_path, p))]
    if not_found:
        print(f"  missing: {', '.join(not_found)}")

    # 3. Extra files (absolute paths, cross-project references)
    for ef in extra_files:
        full = os.path.expanduser(ef)
        if os.path.isfile(full):
            parts = full.split("/")
            label = "/".join(parts[-2:])
            blocks.append(read_file_numbered(full, label))
            file_labels.append(f"  - [EXT] {label}")
            total_files += 1
        else:
            print(f"  extra missing: {ef}")

    content = (
        f"# PRIME CONTEXT: {name}\n"
        f"# {total_files} files pre-loaded, line-numbered, citeable.\n\n"
        f"Files:\n" + "\n".join(file_labels) + "\n\n"
        + "\n".join(blocks)
        + f"\n\nAll {total_files} files loaded.\n\n"
        + "Every entire file from the project codebase is in your context with line numbers. "
        + "YOU ARE BANNED FROM RE-READING these files. "
        + "You are ready to instantly one-shot right within the next 15secs. "
        + "DO NOT OVERTHINK THIS."
    )

    total_chars = len(content)
    est_tokens = total_chars // 4

    stats = {
        "files": total_files,
        "chars": total_chars,
        "tokens": est_tokens,
        "max_tokens": max_tokens,
    }
    return content, stats


def cmd_build(query, dry_run=False):
    """Build context for a project and write to /tmp."""
    # Try local .primerc first if query looks like a path or "."
    name, config = None, None
    if query in (".", "./") or os.path.isdir(query):
        rc_path, proj_dir = find_primerc(query if query != "." else None)
        if rc_path:
            name, config = load_from_primerc(rc_path, proj_dir)
            print(f"  config: {rc_path}")

    # Fall back to central registry
    if not config:
        name, config = load_from_registry(query)

    if not config:
        print(f"No project matching '{query}'.")
        print(f"Options:")
        print(f"  1. Create a .primerc in your project directory")
        print(f"  2. Add it to ~/.prime/projects.json")
        print(f"  3. Run: prime --init  (in your project dir)")
        sys.exit(1)

    abs_path = os.path.expanduser(config["path"])
    print(f"priming: {name}")
    print(f"  path: {abs_path}")

    content, stats = build_context(name, config)

    print(f"  files: {stats['files']}")
    print(f"  chars: {stats['chars']:,}")
    print(f"  ~tokens: {stats['tokens']:,}")

    # Token budget warnings
    if stats["max_tokens"] and stats["tokens"] > stats["max_tokens"]:
        print(f"  WARNING: exceeds max_tokens ({stats['max_tokens']:,})")
    for model, limit in TOKEN_LIMITS.items():
        if stats["tokens"] > limit * 0.8:
            pct = stats["tokens"] / limit * 100
            print(f"  note: {pct:.0f}% of {model} context ({limit:,} tokens)")

    if dry_run:
        print("\n  (dry run — no file written)")
        return None

    slug = re.sub(r"[^a-z0-9]", "-", name.lower()).strip("-")
    out_path = f"/tmp/prime-{slug}.txt"
    with open(out_path, "w") as f:
        f.write(content)
    print(f"  file: {out_path}")

    # Session marker for shell wrapper
    with open("/tmp/prime-session", "w") as f:
        f.write(out_path)

    return out_path


def cmd_list():
    """List all projects in the central registry."""
    if not os.path.isfile(REGISTRY):
        print("No registry found. Create ~/.prime/projects.json or use .primerc files.")
        sys.exit(0)
    with open(REGISTRY) as f:
        projects = json.load(f)
    if not projects:
        print("Registry is empty.")
        sys.exit(0)
    for name, config in sorted(projects.items()):
        kf = len(config.get("key_files", []))
        ef = len(config.get("extra_files", []))
        total = kf + ef
        if total == 0:
            continue
        stack = config.get("stack", "")
        path = config.get("path", "")
        print(f"  {name:<30} {total:>3} files  {stack:<20} {path}")


def cmd_init():
    """Create a .primerc in the current directory by scanning for source files."""
    cwd = os.getcwd()
    name = os.path.basename(cwd)

    # Check if .primerc already exists
    for rc in PRIMERC_NAMES:
        if os.path.isfile(os.path.join(cwd, rc)):
            print(f"Already exists: {rc}")
            print(f"Edit it directly or delete it to re-init.")
            sys.exit(0)

    # Scan for source files, respecting .gitignore patterns
    source_exts = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb",
        ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".hpp",
        ".css", ".html", ".svelte", ".vue", ".json", ".yaml", ".yml",
        ".toml", ".sql", ".sh", ".bash", ".zsh", ".md",
    }
    skip_dirs = {
        "node_modules", ".git", ".next", ".nuxt", "dist", "build",
        "__pycache__", ".venv", "venv", ".tox", "vendor", "target",
        ".cache", ".turbo", "coverage", ".svelte-kit",
    }

    found = []
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in source_exts:
                rel = os.path.relpath(os.path.join(root, fn), cwd)
                found.append(rel)

    found.sort()

    # Estimate tokens
    total_chars = 0
    for f in found:
        try:
            total_chars += os.path.getsize(os.path.join(cwd, f))
        except OSError:
            pass
    est_tokens = total_chars // 4

    rc = {
        "name": name,
        "key_files": found,
        "extra_files": [],
        "skill_file": "",
    }

    rc_path = os.path.join(cwd, ".primerc")
    with open(rc_path, "w") as f:
        json.dump(rc, f, indent=2)
        f.write("\n")

    print(f"Created .primerc with {len(found)} files (~{est_tokens:,} tokens)")
    print(f"Edit {rc_path} to adjust.")

    if est_tokens > TOKEN_LIMIT:
        print(f"\nWARNING: {est_tokens:,} tokens exceeds the 1M context window.")
        print(f"You must reduce key_files to fit.")


def cmd_scan(directory=None):
    """Show what --init would detect without writing anything."""
    cwd = directory or os.getcwd()
    # Reuse init logic but just print
    source_exts = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb",
        ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".hpp",
        ".css", ".html", ".svelte", ".vue",
    }
    skip_dirs = {
        "node_modules", ".git", ".next", ".nuxt", "dist", "build",
        "__pycache__", ".venv", "venv", ".tox", "vendor", "target",
        ".cache", ".turbo", "coverage",
    }
    by_ext = {}
    total_chars = 0
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in source_exts:
                full = os.path.join(root, fn)
                by_ext.setdefault(ext, []).append(full)
                try:
                    total_chars += os.path.getsize(full)
                except OSError:
                    pass

    total_files = sum(len(v) for v in by_ext.values())
    est_tokens = total_chars // 4
    print(f"Scan: {cwd}")
    print(f"  {total_files} source files, ~{est_tokens:,} tokens\n")
    for ext in sorted(by_ext, key=lambda e: -len(by_ext[e])):
        print(f"  {ext:<8} {len(by_ext[ext]):>4} files")

    pct = est_tokens / TOKEN_LIMIT * 100
    status = "OK" if pct < 80 else "TIGHT" if pct < 100 else "TOO LARGE"
    print(f"\n  Context: {pct:.0f}% of 1M window  {status}")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("prime — preload your codebase into Claude Code's context window\n")
        print("Usage:")
        print("  prime <project>     Build context and launch Claude Code")
        print("  prime .             Use .primerc in current directory")
        print("  prime --init        Create .primerc by scanning current directory")
        print("  prime --scan        Show what --init would detect")
        print("  prime --list        List projects in central registry")
        print("  prime --dry-run <p> Show token count without launching")
        print("  prime --version     Show version")
        sys.exit(0)

    if args[0] == "--version":
        print(f"prime {VERSION}")
        sys.exit(0)

    if args[0] == "--list":
        cmd_list()
        sys.exit(0)

    if args[0] == "--init":
        cmd_init()
        sys.exit(0)

    if args[0] == "--scan":
        cmd_scan(args[1] if len(args) > 1 else None)
        sys.exit(0)

    dry_run = "--dry-run" in args
    query_args = [a for a in args if a != "--dry-run"]
    query = " ".join(query_args) if query_args else "."

    cmd_build(query, dry_run=dry_run)


if __name__ == "__main__":
    main()
