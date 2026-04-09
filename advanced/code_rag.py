"""
CodeRAG — Reference Code Mining & Indexing
==========================================
Searches GitHub for relevant reference implementations based on the paper
analysis, downloads them, and builds confidence-scored file mappings between
reference code and the target file structure.

Inspired by DeepCode's codebase indexing workflow, adapted for
Research2Repo's provider-agnostic architecture.

Usage:
    from advanced.code_rag import CodeRAG
    rag = CodeRAG(provider=my_provider)
    index = rag.build_index(analysis, plan)
    context = rag.get_reference_context("model/encoder.py", index)
"""

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from providers.base import BaseProvider, GenerationConfig, ModelCapability
from providers import get_provider


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ReferenceFile:
    """A single file from a reference repository."""
    repo: str                      # e.g. "github_user/repo_name"
    path: str                      # relative path in the reference repo
    content: str = ""              # source code content
    language: str = "python"


@dataclass
class FileMapping:
    """Mapping from a reference file to a target file with a confidence score."""
    reference_file: str            # path in the reference repo
    target_file: str               # path in our generated repo
    confidence: float = 0.0        # 0.0 - 1.0
    relationship: str = "reference"  # direct_match | partial_match | reference | utility
    relevant_snippets: list[str] = field(default_factory=list)


@dataclass
class CodeRAGIndex:
    """Complete index mapping reference code to the target repository."""
    repos_searched: list[str] = field(default_factory=list)
    total_files_indexed: int = 0
    mappings: list[FileMapping] = field(default_factory=list)
    repo_contents: dict[str, list[ReferenceFile]] = field(default_factory=dict)


# Confidence scores by relationship type
_CONFIDENCE_SCORES = {
    "direct_match": 1.0,
    "partial_match": 0.8,
    "reference": 0.6,
    "utility": 0.4,
}

# File extensions to index
_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h",
    ".yaml", ".yml", ".toml", ".json", ".sh",
}

# Directories to skip
_SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", ".vscode", ".idea",
    "dist", "build", "venv", ".venv", "env", ".env", ".egg-info",
}


class CodeRAG:
    """
    Reference Code Retrieval-Augmented Generation.

    Given a paper analysis and architecture plan, this module:
    1. Generates GitHub search queries from the paper's key concepts.
    2. Fetches top matching repositories via the GitHub API.
    3. Downloads and indexes relevant source files.
    4. Uses the LLM to score file-to-file relevance mappings.
    5. Provides targeted reference code snippets during code generation.
    """

    _SEARCH_PROMPT = (
        "Based on this ML paper analysis, generate 3-5 GitHub search queries "
        "to find relevant reference implementations.\n\n"
        "Paper: {title}\n"
        "Architecture: {architecture}\n"
        "Key components: {components}\n\n"
        "Return a JSON object: {{\"queries\": [\"query1\", ...]}}\n"
        "Focus on: model architecture names, algorithm names, framework "
        "patterns (e.g. 'pytorch transformer attention').\n"
        "Respond with ONLY the JSON object."
    )

    _MAPPING_PROMPT = (
        "Analyze this reference code file and determine its relevance to "
        "each target file in the repository being generated.\n\n"
        "## Reference File: {ref_path}\n"
        "```\n{ref_content}\n```\n\n"
        "## Target Files:\n{target_files}\n\n"
        "Return a JSON object:\n"
        '{{"mappings": [\n'
        '  {{"target_file": "path", "relationship": "direct_match|partial_match|reference|utility", '
        '"relevant_snippets": ["snippet1"]}}\n'
        "]}}\n\n"
        "Relationship types:\n"
        "- direct_match: implements the same component\n"
        "- partial_match: implements a related component\n"
        "- reference: useful architectural pattern\n"
        "- utility: helper code that could be adapted\n\n"
        "Only include files with genuine relevance.  Respond with ONLY the JSON."
    )

    def __init__(
        self,
        provider: Optional[BaseProvider] = None,
        max_repos: int = 3,
        max_files_per_repo: int = 20,
        max_file_size: int = 50_000,
    ) -> None:
        self.provider = provider or get_provider(
            required_capability=ModelCapability.TEXT_GENERATION
        )
        self.max_repos = max_repos
        self.max_files_per_repo = max_files_per_repo
        self.max_file_size = max_file_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_index(
        self,
        analysis: "PaperAnalysis",
        plan: "ArchitecturePlan",
        github_token: Optional[str] = None,
    ) -> CodeRAGIndex:
        """
        Build a complete reference code index.

        Args:
            analysis: Paper analysis with title, architecture, components.
            plan: Architecture plan with target file list.
            github_token: Optional GitHub API token for higher rate limits.

        Returns:
            CodeRAGIndex with scored file mappings.
        """
        print("  [CodeRAG] Building reference code index...")
        token = github_token or os.environ.get("GITHUB_TOKEN", "")

        # Step 1: Generate search queries
        queries = self._generate_search_queries(analysis)
        if not queries:
            print("  [CodeRAG] No search queries generated; skipping.")
            return CodeRAGIndex()
        print(f"  [CodeRAG] Generated {len(queries)} search queries.")

        # Step 2: Search GitHub
        repos = self._search_github(queries, token)
        if not repos:
            print("  [CodeRAG] No repositories found; skipping.")
            return CodeRAGIndex()
        print(f"  [CodeRAG] Found {len(repos)} candidate repositories.")

        # Step 3: Fetch repository contents
        index = CodeRAGIndex(repos_searched=[r["full_name"] for r in repos])
        for repo_info in repos[:self.max_repos]:
            repo_name = repo_info["full_name"]
            print(f"  [CodeRAG] Indexing {repo_name}...")
            files = self._fetch_repo_files(repo_name, token)
            if files:
                index.repo_contents[repo_name] = files
                index.total_files_indexed += len(files)

        if index.total_files_indexed == 0:
            print("  [CodeRAG] No files fetched; skipping mapping.")
            return index

        # Step 4: Build relevance mappings
        target_files = [f.path for f in plan.files]
        index.mappings = self._build_mappings(index.repo_contents, target_files)

        high_conf = sum(1 for m in index.mappings if m.confidence >= 0.8)
        print(f"  [CodeRAG] Index complete: {index.total_files_indexed} files indexed, "
              f"{len(index.mappings)} mappings ({high_conf} high-confidence).")
        return index

    def get_reference_context(
        self,
        target_file: str,
        index: CodeRAGIndex,
        max_snippets: int = 3,
        max_chars: int = 4000,
    ) -> str:
        """
        Retrieve reference code snippets relevant to a target file.

        Args:
            target_file: Path of the file being generated.
            index: Pre-built CodeRAGIndex.
            max_snippets: Maximum number of reference snippets to include.
            max_chars: Maximum total character count for the context.

        Returns:
            Formatted string with reference code snippets.
        """
        relevant = [
            m for m in index.mappings
            if m.target_file == target_file
        ]
        relevant.sort(key=lambda m: m.confidence, reverse=True)

        if not relevant:
            return ""

        parts = ["## Reference Code (from similar implementations)"]
        total_chars = 0

        for mapping in relevant[:max_snippets]:
            # Find the actual file content
            content = self._find_file_content(
                mapping.reference_file, index.repo_contents
            )
            if not content:
                continue

            # Use snippets if available, else truncate full content
            if mapping.relevant_snippets:
                snippet_text = "\n\n".join(mapping.relevant_snippets)
            else:
                snippet_text = content[:2000]
                if len(content) > 2000:
                    snippet_text += "\n# ... (truncated)"

            if total_chars + len(snippet_text) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 200:
                    snippet_text = snippet_text[:remaining] + "\n# ... (truncated)"
                else:
                    break

            rel_label = mapping.relationship.replace("_", " ").title()
            conf_pct = int(mapping.confidence * 100)
            parts.append(
                f"\n### {mapping.reference_file} "
                f"({rel_label}, {conf_pct}% relevant)\n"
                f"```python\n{snippet_text}\n```"
            )
            total_chars += len(snippet_text)

        return "\n".join(parts) if len(parts) > 1 else ""

    # ------------------------------------------------------------------
    # Internal: Search queries
    # ------------------------------------------------------------------

    def _generate_search_queries(self, analysis: "PaperAnalysis") -> list[str]:
        """Use LLM to generate targeted GitHub search queries."""
        components = ", ".join(
            getattr(analysis, "key_contributions", [])[:5]
        )

        prompt = self._SEARCH_PROMPT.format(
            title=analysis.title,
            architecture=analysis.architecture_description[:500],
            components=components,
        )

        try:
            result = self.provider.generate(
                prompt=prompt,
                system_prompt="You are an expert at finding ML code on GitHub.",
                config=GenerationConfig(temperature=0.2, max_output_tokens=1024),
            )
            data = self._parse_json(result.text)
            return data.get("queries", [])[:5]
        except Exception as exc:
            print(f"  [CodeRAG] Query generation failed ({exc}); using fallback.")
            # Fallback: construct queries from paper metadata
            queries = []
            if analysis.title:
                queries.append(f"pytorch {analysis.title.lower()[:60]}")
            if analysis.architecture_description:
                words = analysis.architecture_description.split()[:6]
                queries.append(f"python {' '.join(words)}")
            return queries[:3]

    # ------------------------------------------------------------------
    # Internal: GitHub search
    # ------------------------------------------------------------------

    def _search_github(
        self, queries: list[str], token: str
    ) -> list[dict]:
        """Search GitHub for repositories matching the queries."""
        try:
            import requests
        except ImportError:
            print("  [CodeRAG] requests not installed; skipping GitHub search.")
            return []

        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"

        seen = set()
        results = []

        for query in queries:
            try:
                resp = requests.get(
                    "https://api.github.com/search/repositories",
                    params={
                        "q": f"{query} language:python",
                        "sort": "stars",
                        "per_page": 5,
                    },
                    headers=headers,
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue

                for item in resp.json().get("items", []):
                    full_name = item.get("full_name", "")
                    if full_name and full_name not in seen:
                        seen.add(full_name)
                        results.append({
                            "full_name": full_name,
                            "stars": item.get("stargazers_count", 0),
                            "description": item.get("description", ""),
                            "default_branch": item.get("default_branch", "main"),
                        })
            except Exception:
                continue

        # Sort by stars
        results.sort(key=lambda r: r.get("stars", 0), reverse=True)
        return results[:self.max_repos * 2]

    # ------------------------------------------------------------------
    # Internal: Fetch repo files
    # ------------------------------------------------------------------

    def _fetch_repo_files(
        self, repo_name: str, token: str
    ) -> list[ReferenceFile]:
        """Fetch source files from a GitHub repository via the API."""
        try:
            import requests
        except ImportError:
            return []

        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"

        files = []

        try:
            # Get the repo tree recursively
            resp = requests.get(
                f"https://api.github.com/repos/{repo_name}/git/trees/HEAD",
                params={"recursive": "1"},
                headers=headers,
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            tree = resp.json().get("tree", [])

            # Filter to code files
            candidates = []
            for item in tree:
                if item.get("type") != "blob":
                    continue
                path = item.get("path", "")
                ext = os.path.splitext(path)[1].lower()
                if ext not in _CODE_EXTENSIONS:
                    continue
                # Skip files in excluded directories
                parts = path.split("/")
                if any(p in _SKIP_DIRS for p in parts):
                    continue
                size = item.get("size", 0)
                if size > self.max_file_size:
                    continue
                candidates.append(path)

            # Prioritise: model/train/data files first, then by path length
            def _priority(p: str) -> int:
                lower = p.lower()
                if any(k in lower for k in ("model", "train", "loss", "network")):
                    return 0
                if any(k in lower for k in ("data", "dataset", "loader")):
                    return 1
                if any(k in lower for k in ("config", "utils", "eval")):
                    return 2
                return 3

            candidates.sort(key=lambda p: (_priority(p), len(p)))
            candidates = candidates[:self.max_files_per_repo]

            # Fetch content
            for path in candidates:
                try:
                    content_resp = requests.get(
                        f"https://api.github.com/repos/{repo_name}/contents/{path}",
                        headers={**headers, "Accept": "application/vnd.github.v3.raw"},
                        timeout=10,
                    )
                    if content_resp.status_code == 200:
                        files.append(ReferenceFile(
                            repo=repo_name,
                            path=path,
                            content=content_resp.text[:self.max_file_size],
                            language=os.path.splitext(path)[1].lstrip("."),
                        ))
                except Exception:
                    continue

        except Exception as exc:
            print(f"  [CodeRAG] Failed to fetch {repo_name}: {exc}")

        return files

    # ------------------------------------------------------------------
    # Internal: Build mappings
    # ------------------------------------------------------------------

    def _build_mappings(
        self,
        repo_contents: dict[str, list[ReferenceFile]],
        target_files: list[str],
    ) -> list[FileMapping]:
        """Use LLM to map reference files to target files with confidence."""
        target_listing = "\n".join(f"  - {f}" for f in target_files)
        mappings: list[FileMapping] = []

        for repo_name, files in repo_contents.items():
            for ref_file in files:
                # Skip very small files
                if len(ref_file.content.strip()) < 50:
                    continue

                # Truncate for prompt
                content_for_prompt = ref_file.content[:3000]
                if len(ref_file.content) > 3000:
                    content_for_prompt += "\n# ... (truncated)"

                prompt = self._MAPPING_PROMPT.format(
                    ref_path=f"{repo_name}/{ref_file.path}",
                    ref_content=content_for_prompt,
                    target_files=target_listing,
                )

                try:
                    result = self.provider.generate(
                        prompt=prompt,
                        system_prompt=(
                            "You are an expert code analyst.  Determine file-level "
                            "relevance between reference code and target files."
                        ),
                        config=GenerationConfig(
                            temperature=0.1,
                            max_output_tokens=2048,
                        ),
                    )
                    data = self._parse_json(result.text)
                    for m in data.get("mappings", []):
                        relationship = m.get("relationship", "reference")
                        confidence = _CONFIDENCE_SCORES.get(relationship, 0.5)
                        mappings.append(FileMapping(
                            reference_file=f"{repo_name}/{ref_file.path}",
                            target_file=m.get("target_file", ""),
                            confidence=confidence,
                            relationship=relationship,
                            relevant_snippets=m.get("relevant_snippets", []),
                        ))
                except Exception:
                    continue

        return mappings

    # ------------------------------------------------------------------
    # Internal: Utilities
    # ------------------------------------------------------------------

    def _find_file_content(
        self,
        reference_path: str,
        repo_contents: dict[str, list[ReferenceFile]],
    ) -> str:
        """Look up the content of a reference file by its full path."""
        for repo_name, files in repo_contents.items():
            for f in files:
                full_path = f"{repo_name}/{f.path}"
                if full_path == reference_path:
                    return f.content
        return ""

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Parse JSON from model output, handling markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
