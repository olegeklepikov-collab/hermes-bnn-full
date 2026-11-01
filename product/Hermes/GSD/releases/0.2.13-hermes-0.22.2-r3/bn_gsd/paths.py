from pathlib import Path


def scoped_public_file(raw, roots):
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("Use an absolute addressed file path")
    path = candidate.resolve()
    if not any(path.is_relative_to(Path(root).resolve()) for root in roots):
        raise ValueError("Read is outside the approved workspace/corpus")
    if not path.is_file():
        raise ValueError("An existing regular file is required")
    names = {part.lower() for part in path.parts}
    if names & {".ssh", ".aws", ".gnupg", "mcp-tokens", "auth.json"} or path.name.lower().startswith(".env") or path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
        raise ValueError("Credential paths are outside the analysis read scope")
    return path


def public_read_roots(settings):
    root=Path(settings["runtime_root"])
    roots=[Path(settings["workspace"]),Path(settings["bundle_root"])]
    for provider in ["ASReview","AlphaXiv","Beads","Dolt","Crossref","Firecrawl","Keenable","Nimble","OpenAlex","Parallel","PubMed","R","RussianResearch","SemanticScholar","Tavily","Zotero"]:
        for name in ["exports","inbox","projects","downloads","content"]:
            path=root/provider/name
            if path.is_dir():roots.append(path.resolve())
    skills=root/"data/skills"
    if skills.is_dir():roots.append(skills.resolve())
    for name in ["spillover","web","images"]:
        path=root/"data/cache"/name
        if path.is_dir():roots.append(path.resolve())
    return roots
