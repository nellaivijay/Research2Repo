"""
ContextManager — Concise Memory & Cumulative Code Summaries
============================================================
Manages LLM context during multi-file code generation to prevent
context window overflow while maintaining cross-file coherence.

Implements a "clean-slate" approach inspired by DeepCode's memory agent:
after each file is generated, the full conversation is discarded and
replaced with: system prompt + architecture plan + cumulative code
summary + current file context.

Usage:
    from advanced.context_manager import ContextManager
    ctx = ContextManager(plan=my_plan, analysis=my_analysis)
    for file_spec in plan.files:
        prompt = ctx.build_prompt(file_spec)
        code = generate(prompt)
        ctx.record_file(file_spec.path, code)
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from providers.base import BaseProvider, GenerationConfig, ModelCapability
from providers import get_provider


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FileSummary:
    """Compact summary of a generated file."""
    path: str = ""
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    key_algorithms: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    line_count: int = 0


@dataclass
class GenerationContext:
    """The assembled context for generating a single file."""
    system_prompt: str = ""
    plan_summary: str = ""
    code_summary: str = ""
    reference_context: str = ""
    file_instruction: str = ""
    dependency_code: str = ""

    def full_prompt(self) -> str:
        """Assemble all context parts into a single prompt."""
        parts = [p for p in [
            self.plan_summary,
            self.code_summary,
            self.reference_context,
            self.dependency_code,
            self.file_instruction,
        ] if p]
        return "\n\n".join(parts)

    def estimated_tokens(self) -> int:
        """Rough token estimate (~4 chars per token)."""
        total = len(self.system_prompt) + len(self.full_prompt())
        return total // 4


class ContextManager:
    """
    Manages context for multi-file code generation.

    Core design:
    - Maintains a *cumulative code summary* that grows as files are generated.
    - For each new file, builds a fresh context with:
        1. Architecture plan summary (always included)
        2. Cumulative code summary (compressed representation of all prior files)
        3. Full source code of direct dependencies only
        4. Reference code from CodeRAG (if available)
        5. File-specific generation instructions
    - Optionally uses the LLM to generate compressed file summaries
      (falls back to heuristic extraction if LLM is unavailable).

    This "clean-slate" approach prevents context window overflow while
    preserving the information the LLM needs for cross-file coherence.
    """

    def __init__(
        self,
        plan: "ArchitecturePlan",
        analysis: "PaperAnalysis",
        provider: Optional[BaseProvider] = None,
        max_context_chars: int = 80_000,
        max_dependency_chars: int = 12_000,
        use_llm_summaries: bool = True,
    ) -> None:
        """
        Args:
            plan: Architecture plan with file list.
            analysis: Paper analysis (equations, hyperparams, etc.).
            provider: LLM provider for summary generation.
            max_context_chars: Target max chars for the assembled context.
            max_dependency_chars: Max chars for dependency code inclusion.
            use_llm_summaries: Whether to use LLM for file summarisation.
        """
        self._plan = plan
        self._analysis = analysis
        self._provider = provider
        self._max_context = max_context_chars
        self._max_dep_chars = max_dependency_chars
        self._use_llm = use_llm_summaries and provider is not None

        # State
        self._generated_files: dict[str, str] = {}     # path -> full code
        self._file_summaries: list[FileSummary] = []    # ordered
        self._cumulative_summary: str = ""              # growing text summary

        # Pre-compute plan summary (static)
        self._plan_summary = self._build_plan_summary()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_context(
        self,
        file_spec: "FileSpec",
        reference_context: str = "",
    ) -> GenerationContext:
        """
        Build a fresh generation context for a file.

        Args:
            file_spec: The file to generate.
            reference_context: Optional CodeRAG reference code string.

        Returns:
            GenerationContext with all parts assembled.
        """
        ctx = GenerationContext(
            system_prompt=self._system_prompt(),
            plan_summary=self._plan_summary,
            code_summary=self._build_cumulative_section(),
            reference_context=reference_context,
            dependency_code=self._build_dependency_code(file_spec),
            file_instruction=self._build_file_instruction(file_spec),
        )

        # Budget check: if over limit, trim the reference context
        est = ctx.estimated_tokens()
        max_tokens = self._max_context // 4
        if est > max_tokens and ctx.reference_context:
            excess = (est - max_tokens) * 4
            ctx.reference_context = ctx.reference_context[:-excess] if excess < len(ctx.reference_context) else ""

        return ctx

    def record_file(self, path: str, code: str) -> None:
        """
        Record a generated file and update the cumulative summary.

        Call this after each file is successfully generated.

        Args:
            path: File path (relative, e.g. "model/encoder.py").
            code: The generated source code.
        """
        self._generated_files[path] = code

        # Generate summary
        summary = self._summarise_file(path, code)
        self._file_summaries.append(summary)

        # Update cumulative summary
        self._cumulative_summary = self._rebuild_cumulative_summary()

        print(f"  [ContextMgr] Recorded {path} "
              f"({summary.line_count} lines, "
              f"{len(summary.classes)} classes, "
              f"{len(summary.functions)} functions)")

    def get_cumulative_summary(self) -> str:
        """Return the current cumulative code summary."""
        return self._cumulative_summary

    def files_generated(self) -> int:
        """Return the number of files generated so far."""
        return len(self._generated_files)

    def save_summary(self, output_dir: str) -> str:
        """
        Save the cumulative summary to disk.

        Args:
            output_dir: Directory to write the summary file.

        Returns:
            Path to the saved summary file.
        """
        path = os.path.join(output_dir, ".r2r_code_summary.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# Code Summary\n\n")
            fh.write(f"Generated {len(self._file_summaries)} files.\n\n")
            fh.write(self._cumulative_summary)
        return path

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def _system_prompt(self) -> str:
        return (
            "You are an expert ML engineer writing production-quality Python code. "
            "You implement research papers faithfully, with exact equations, "
            "correct tensor dimensions, and proper loss functions. "
            "Output ONLY the file content — no explanations, no markdown fences."
        )

    def _build_plan_summary(self) -> str:
        """Build a static summary of the architecture plan."""
        parts = [
            f"# Paper: {self._analysis.title}",
            f"\n## Architecture\n{self._analysis.architecture_description}",
        ]

        # Equations (up to 15)
        if self._analysis.equations:
            parts.append("\n## Key Equations")
            for eq in self._analysis.equations[:15]:
                parts.append(f"  - {eq}")

        # Hyperparameters
        if self._analysis.hyperparameters:
            parts.append("\n## Hyperparameters")
            for k, v in list(self._analysis.hyperparameters.items())[:15]:
                parts.append(f"  - {k}: {v}")

        # Loss functions
        if self._analysis.loss_functions:
            parts.append("\n## Loss Functions")
            for lf in self._analysis.loss_functions:
                parts.append(f"  - {lf}")

        # Directory structure
        parts.append(f"\n## Repository Structure\n{self._plan.directory_tree}")

        # File list
        parts.append("\n## Files")
        for fs in self._plan.files:
            parts.append(f"  - {fs.path}: {fs.description}")

        return "\n".join(parts)

    def _build_cumulative_section(self) -> str:
        """Build the cumulative code summary section."""
        if not self._cumulative_summary:
            return ""
        return (
            "## Previously Generated Files (Summary)\n"
            "Use these summaries to maintain consistency with earlier files.\n\n"
            + self._cumulative_summary
        )

    def _build_dependency_code(self, file_spec: "FileSpec") -> str:
        """Include full source of direct dependencies (up to char limit)."""
        if not file_spec.dependencies:
            return ""

        parts = ["## Direct Dependencies (full source)"]
        total_chars = 0

        for dep_path in file_spec.dependencies:
            if dep_path not in self._generated_files:
                continue

            code = self._generated_files[dep_path]
            if total_chars + len(code) > self._max_dep_chars:
                # Truncate
                remaining = self._max_dep_chars - total_chars
                if remaining > 500:
                    code = code[:remaining] + "\n# ... (truncated)"
                else:
                    break

            parts.append(f"\n### {dep_path}\n```python\n{code}\n```")
            total_chars += len(code)

        return "\n".join(parts) if len(parts) > 1 else ""

    def _build_file_instruction(self, file_spec: "FileSpec") -> str:
        """Build the file-specific generation instruction."""
        return (
            f"---\n\n"
            f"## YOUR TASK\n"
            f"Generate the complete content for: **{file_spec.path}**\n\n"
            f"Description: {file_spec.description}\n\n"
            f"Requirements:\n"
            f"- Implement EXACTLY what the paper describes\n"
            f"- Include docstrings and type hints\n"
            f"- Embed relevant equations as comments (LaTeX in docstrings)\n"
            f"- Use config references for hyperparameters, not hardcoded values\n"
            f"- Follow PyTorch conventions where applicable\n"
            f"- Make imports explicit — reference files from the repo structure\n"
            f"- Output ONLY the file content, no explanations\n"
        )

    # ------------------------------------------------------------------
    # File summarisation
    # ------------------------------------------------------------------

    def _summarise_file(self, path: str, code: str) -> FileSummary:
        """Generate a compact summary of a file."""
        if self._use_llm:
            try:
                return self._summarise_with_llm(path, code)
            except Exception:
                pass
        return self._summarise_heuristic(path, code)

    def _summarise_with_llm(self, path: str, code: str) -> FileSummary:
        """Use LLM to generate a structured file summary."""
        prompt = (
            f"Summarise this Python file concisely for use as context in "
            f"generating other files.\n\n"
            f"File: {path}\n```python\n{code[:6000]}\n```\n\n"
            f"Return a JSON object:\n"
            f'{{"classes": ["ClassName(base): description"], '
            f'"functions": ["func_name(args) -> ret: description"], '
            f'"key_algorithms": ["brief description"], '
            f'"imports": ["import statement"], '
            f'"dependencies": ["project_file_path"]}}\n\n'
            f"Respond with ONLY the JSON."
        )

        result = self._provider.generate(
            prompt=prompt,
            system_prompt="You are a code analyst. Produce concise file summaries.",
            config=GenerationConfig(temperature=0.1, max_output_tokens=1024),
        )

        data = self._parse_json(result.text)
        return FileSummary(
            path=path,
            classes=data.get("classes", []),
            functions=data.get("functions", []),
            key_algorithms=data.get("key_algorithms", []),
            imports=data.get("imports", []),
            dependencies=data.get("dependencies", []),
            line_count=code.count("\n") + 1,
        )

    @staticmethod
    def _summarise_heuristic(path: str, code: str) -> FileSummary:
        """Extract summary from code using regex heuristics."""
        import re

        classes = re.findall(r"^class\s+(\w+)(?:\([^)]*\))?:", code, re.MULTILINE)
        functions = re.findall(r"^def\s+(\w+)\s*\(", code, re.MULTILINE)
        imports = re.findall(r"^(?:from\s+\S+\s+)?import\s+.+$", code, re.MULTILINE)

        # Extract project-internal imports
        deps = []
        for imp in imports:
            match = re.match(r"from\s+(\S+)\s+import", imp)
            if match:
                module = match.group(1)
                if not module.startswith(("os", "sys", "re", "json", "math",
                                         "typing", "dataclass", "abc",
                                         "torch", "numpy", "scipy",
                                         "sklearn", "transformers",
                                         "collections", "pathlib",
                                         "functools", "itertools")):
                    dep_path = module.replace(".", "/") + ".py"
                    deps.append(dep_path)

        return FileSummary(
            path=path,
            classes=classes,
            functions=[f for f in functions if not f.startswith("_")],
            key_algorithms=[],
            imports=imports[:10],
            dependencies=deps,
            line_count=code.count("\n") + 1,
        )

    # ------------------------------------------------------------------
    # Cumulative summary
    # ------------------------------------------------------------------

    def _rebuild_cumulative_summary(self) -> str:
        """Rebuild the full cumulative summary from all file summaries."""
        parts = []

        for fs in self._file_summaries:
            file_part = [f"### {fs.path} ({fs.line_count} lines)"]

            if fs.classes:
                file_part.append("  Classes: " + ", ".join(fs.classes[:5]))
            if fs.functions:
                file_part.append("  Functions: " + ", ".join(fs.functions[:8]))
            if fs.key_algorithms:
                file_part.append("  Algorithms: " + "; ".join(fs.key_algorithms[:3]))
            if fs.dependencies:
                file_part.append("  Deps: " + ", ".join(fs.dependencies[:5]))

            parts.append("\n".join(file_part))

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Parse JSON from model output, handling markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
