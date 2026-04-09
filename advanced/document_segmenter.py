"""
DocumentSegmenter — Semantic Chunking for Large Research Papers
===============================================================
Intelligently segments papers that exceed LLM token limits using
content-aware strategies that preserve algorithm blocks, equation
chains, and logical section boundaries.

Inspired by DeepCode's document segmentation approach, adapted for
Research2Repo's provider-agnostic pipeline.

Usage:
    from advanced.document_segmenter import DocumentSegmenter
    segmenter = DocumentSegmenter(provider=my_provider)
    segments = segmenter.segment(paper_text)
    relevant = segmenter.query_segments(segments, "attention mechanism")
"""

import math
import re
from dataclasses import dataclass, field
from typing import Optional

from providers.base import BaseProvider, GenerationConfig, ModelCapability
from providers import get_provider


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    """A semantically coherent chunk of a research paper."""
    content: str = ""
    section_name: str = ""
    segment_type: str = "text"     # text | algorithm | equation_block | table | abstract | methods
    start_line: int = 0
    end_line: int = 0
    importance: float = 0.5        # 0.0 - 1.0, how critical for code generation
    keywords: list[str] = field(default_factory=list)


@dataclass
class SegmentationResult:
    """Output of the document segmentation pipeline."""
    segments: list[Segment] = field(default_factory=list)
    strategy: str = ""
    doc_type: str = ""
    total_chars: int = 0
    algorithm_density: float = 0.0
    concept_complexity: float = 0.0


# ---------------------------------------------------------------------------
# Segmentation strategies
# ---------------------------------------------------------------------------

# Regex patterns for detecting key document structures
_ALGORITHM_PATTERN = re.compile(
    r"(?:Algorithm\s+\d+|Procedure\s+\d+|ALGORITHM\s+\d+|"
    r"\\begin\{algorithm\}|Input:|Output:|"
    r"(?:for|while|repeat|if)\s+(?:each|all|i\s*=))",
    re.IGNORECASE,
)

_EQUATION_PATTERN = re.compile(
    r"(?:\\begin\{(?:equation|align|gather)\}|"
    r"\$\$[^$]+\$\$|"
    r"\\(?:frac|sum|prod|int|nabla|partial)\{|"
    r"(?:^|\n)\s*[A-Z]\s*=\s*\S)",
    re.MULTILINE,
)

_SECTION_PATTERN = re.compile(
    r"^(?:\d+\.?\s+|#{1,3}\s+|\\(?:section|subsection)\{)"
    r"([A-Z][\w\s,&-]{2,60})",
    re.MULTILINE,
)

_TABLE_PATTERN = re.compile(
    r"(?:Table\s+\d+|\\begin\{(?:table|tabular)\}|"
    r"\|[-:]+\|)",  # markdown tables
    re.IGNORECASE,
)

# Strategy names
STRATEGY_SEMANTIC_RESEARCH = "semantic_research_focused"
STRATEGY_ALGORITHM_PRESERVE = "algorithm_preserve_integrity"
STRATEGY_CONCEPT_HYBRID = "concept_implementation_hybrid"
STRATEGY_CONTENT_AWARE = "content_aware_segmentation"


class DocumentSegmenter:
    """
    Segments research papers into semantically meaningful chunks.

    Chooses a segmentation strategy based on document characteristics
    (algorithm density, equation complexity, document type), then produces
    chunks that respect logical boundaries while staying within token limits.

    Key features:
    - Algorithm block detection and preservation (never splits mid-algorithm)
    - Equation chain grouping (keeps related equations together)
    - Section-aware splitting with overlap
    - Importance scoring per segment for priority retrieval
    - Query-aware segment retrieval with relevance ranking
    """

    # Default token limit per segment (conservative; ~4 chars/token)
    DEFAULT_MAX_CHARS = 12_000

    # Overlap between segments for context continuity
    DEFAULT_OVERLAP_CHARS = 500

    def __init__(
        self,
        provider: Optional[BaseProvider] = None,
        max_chars_per_segment: int = DEFAULT_MAX_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    ) -> None:
        self.provider = provider  # Optional — only needed for query retrieval
        self.max_chars = max_chars_per_segment
        self.overlap = overlap_chars

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def segment(self, text: str, force_strategy: Optional[str] = None) -> SegmentationResult:
        """
        Segment a paper into semantically coherent chunks.

        Args:
            text: Full extracted text of the research paper.
            force_strategy: Override automatic strategy selection.

        Returns:
            SegmentationResult with scored segments.
        """
        if not text.strip():
            return SegmentationResult()

        total_chars = len(text)

        # If text fits in a single chunk, return as-is
        if total_chars <= self.max_chars:
            seg = Segment(
                content=text,
                section_name="full_paper",
                segment_type="text",
                importance=1.0,
            )
            return SegmentationResult(
                segments=[seg],
                strategy="no_split_needed",
                total_chars=total_chars,
            )

        # Analyse document characteristics
        alg_density = self._algorithm_density(text)
        concept_complexity = self._concept_complexity(text)
        doc_type = self._classify_document(text, alg_density, concept_complexity)

        # Choose strategy
        strategy = force_strategy or self._choose_strategy(
            doc_type, alg_density, concept_complexity
        )
        print(f"  [Segmenter] Doc type: {doc_type} | "
              f"Strategy: {strategy} | "
              f"Alg density: {alg_density:.2f} | "
              f"Complexity: {concept_complexity:.2f}")

        # Execute strategy
        segments = self._execute_strategy(text, strategy)

        # Score importance
        segments = self._score_importance(segments, doc_type)

        return SegmentationResult(
            segments=segments,
            strategy=strategy,
            doc_type=doc_type,
            total_chars=total_chars,
            algorithm_density=alg_density,
            concept_complexity=concept_complexity,
        )

    def query_segments(
        self,
        result: SegmentationResult,
        query: str,
        query_type: str = "general",
        top_k: int = 3,
    ) -> list[Segment]:
        """
        Retrieve the most relevant segments for a query.

        Args:
            result: Pre-computed SegmentationResult.
            query: What we're looking for (e.g. "attention mechanism").
            query_type: One of "concept_analysis", "algorithm_extraction",
                        "code_planning", "general".
            top_k: Number of segments to return.

        Returns:
            List of the most relevant segments, sorted by score.
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored: list[tuple[float, Segment]] = []

        for seg in result.segments:
            score = self._relevance_score(seg, query_words, query_type)
            scored.append((score, seg))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [seg for _, seg in scored[:top_k]]

    # ------------------------------------------------------------------
    # Document analysis
    # ------------------------------------------------------------------

    def _algorithm_density(self, text: str) -> float:
        """Score how algorithm-heavy the paper is (0.0 - 1.0)."""
        matches = _ALGORITHM_PATTERN.findall(text)
        # Normalise: 10+ algorithm markers = density 1.0
        return min(len(matches) / 10.0, 1.0)

    def _concept_complexity(self, text: str) -> float:
        """Score equation/concept complexity (0.0 - 1.0)."""
        eq_matches = _EQUATION_PATTERN.findall(text)
        # Normalise: 30+ equation blocks = complexity 1.0
        return min(len(eq_matches) / 30.0, 1.0)

    def _classify_document(
        self, text: str, alg_density: float, concept_complexity: float
    ) -> str:
        """Classify document type based on content analysis."""
        text_lower = text[:5000].lower()

        if alg_density > 0.6:
            return "algorithm_focused"
        if concept_complexity > 0.7:
            return "math_heavy"
        if any(kw in text_lower for kw in ("neural network", "deep learning", "transformer")):
            return "deep_learning"
        if any(kw in text_lower for kw in ("training", "loss function", "gradient")):
            return "ml_training"
        return "research_paper"

    def _choose_strategy(
        self, doc_type: str, alg_density: float, concept_complexity: float
    ) -> str:
        """Select the best segmentation strategy."""
        if alg_density > 0.5:
            return STRATEGY_ALGORITHM_PRESERVE
        if concept_complexity > 0.5 and alg_density > 0.3:
            return STRATEGY_CONCEPT_HYBRID
        if doc_type in ("deep_learning", "ml_training"):
            return STRATEGY_CONTENT_AWARE
        return STRATEGY_SEMANTIC_RESEARCH

    # ------------------------------------------------------------------
    # Strategy execution
    # ------------------------------------------------------------------

    def _execute_strategy(self, text: str, strategy: str) -> list[Segment]:
        """Execute the chosen segmentation strategy."""
        if strategy == STRATEGY_ALGORITHM_PRESERVE:
            return self._segment_algorithm_preserve(text)
        if strategy == STRATEGY_CONCEPT_HYBRID:
            return self._segment_concept_hybrid(text)
        if strategy == STRATEGY_CONTENT_AWARE:
            return self._segment_content_aware(text)
        return self._segment_semantic_research(text)

    def _segment_semantic_research(self, text: str) -> list[Segment]:
        """
        Default strategy: split by detected sections, respecting boundaries.
        """
        sections = self._split_by_sections(text)
        segments = []

        for section_name, section_text in sections:
            if len(section_text) <= self.max_chars:
                segments.append(Segment(
                    content=section_text,
                    section_name=section_name,
                    segment_type=self._detect_segment_type(section_text),
                ))
            else:
                # Sub-split large sections by paragraphs
                sub_segs = self._split_by_paragraphs(
                    section_text, section_name
                )
                segments.extend(sub_segs)

        return segments

    def _segment_algorithm_preserve(self, text: str) -> list[Segment]:
        """
        Strategy for algorithm-heavy papers: identify algorithm blocks
        first and protect them from splitting.
        """
        # Extract algorithm blocks
        alg_blocks = self._extract_algorithm_blocks(text)

        # Mark algorithm regions in the text
        segments = []
        last_end = 0

        for alg_start, alg_end, alg_text in alg_blocks:
            # Text before this algorithm
            if alg_start > last_end:
                pre_text = text[last_end:alg_start]
                if pre_text.strip():
                    sections = self._split_by_sections(pre_text)
                    for name, content in sections:
                        if len(content) <= self.max_chars:
                            segments.append(Segment(
                                content=content,
                                section_name=name,
                                segment_type="text",
                            ))
                        else:
                            segments.extend(
                                self._split_by_paragraphs(content, name)
                            )

            # The algorithm block itself (never split)
            segments.append(Segment(
                content=alg_text,
                section_name="Algorithm",
                segment_type="algorithm",
                importance=0.95,
            ))
            last_end = alg_end

        # Remaining text after last algorithm
        if last_end < len(text):
            remaining = text[last_end:]
            if remaining.strip():
                sections = self._split_by_sections(remaining)
                for name, content in sections:
                    if len(content) <= self.max_chars:
                        segments.append(Segment(
                            content=content,
                            section_name=name,
                            segment_type="text",
                        ))
                    else:
                        segments.extend(
                            self._split_by_paragraphs(content, name)
                        )

        return segments

    def _segment_concept_hybrid(self, text: str) -> list[Segment]:
        """
        Strategy for papers with both algorithms and heavy math:
        preserve both algorithm blocks and equation chains.
        """
        # First pass: split by sections
        sections = self._split_by_sections(text)
        segments = []

        for section_name, section_text in sections:
            # Check if this section has equation blocks
            eq_blocks = self._extract_equation_chains(section_text)

            if eq_blocks and len(section_text) > self.max_chars:
                # Split around equation chains
                sub_segs = self._split_preserving_equations(
                    section_text, section_name, eq_blocks
                )
                segments.extend(sub_segs)
            elif len(section_text) <= self.max_chars:
                seg_type = self._detect_segment_type(section_text)
                segments.append(Segment(
                    content=section_text,
                    section_name=section_name,
                    segment_type=seg_type,
                ))
            else:
                segments.extend(
                    self._split_by_paragraphs(section_text, section_name)
                )

        return segments

    def _segment_content_aware(self, text: str) -> list[Segment]:
        """
        Strategy for ML/DL papers: prioritise architecture, training,
        and loss function sections.
        """
        sections = self._split_by_sections(text)
        segments = []

        for section_name, section_text in sections:
            seg_type = self._detect_segment_type(section_text)

            if len(section_text) <= self.max_chars:
                segments.append(Segment(
                    content=section_text,
                    section_name=section_name,
                    segment_type=seg_type,
                ))
            else:
                # For method/architecture sections, use smaller chunks
                # for better granularity
                max_chars = self.max_chars
                name_lower = section_name.lower()
                if any(k in name_lower for k in (
                    "method", "model", "architecture", "approach"
                )):
                    max_chars = self.max_chars // 2

                sub_segs = self._split_by_paragraphs(
                    section_text, section_name, max_chars=max_chars
                )
                segments.extend(sub_segs)

        return segments

    # ------------------------------------------------------------------
    # Text splitting utilities
    # ------------------------------------------------------------------

    def _split_by_sections(self, text: str) -> list[tuple[str, str]]:
        """Split text into (section_name, section_text) pairs."""
        matches = list(_SECTION_PATTERN.finditer(text))

        if not matches:
            return [("unknown", text)]

        sections = []
        for i, match in enumerate(matches):
            name = match.group(1).strip()
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            if content:
                sections.append((name, content))

        # Include text before first section header
        if matches and matches[0].start() > 0:
            preamble = text[:matches[0].start()].strip()
            if preamble:
                sections.insert(0, ("preamble", preamble))

        return sections if sections else [("unknown", text)]

    def _split_by_paragraphs(
        self,
        text: str,
        section_name: str,
        max_chars: Optional[int] = None,
    ) -> list[Segment]:
        """Split a section into paragraph-based chunks."""
        max_c = max_chars or self.max_chars
        paragraphs = re.split(r"\n\s*\n", text)

        segments = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 2 <= max_c:
                current_chunk += ("\n\n" + para) if current_chunk else para
            else:
                if current_chunk:
                    segments.append(Segment(
                        content=current_chunk,
                        section_name=section_name,
                        segment_type=self._detect_segment_type(current_chunk),
                    ))
                # Start new chunk; include overlap from end of previous
                if self.overlap and current_chunk:
                    overlap_text = current_chunk[-self.overlap:]
                    current_chunk = overlap_text + "\n\n" + para
                else:
                    current_chunk = para

        if current_chunk.strip():
            segments.append(Segment(
                content=current_chunk,
                section_name=section_name,
                segment_type=self._detect_segment_type(current_chunk),
            ))

        return segments

    def _extract_algorithm_blocks(self, text: str) -> list[tuple[int, int, str]]:
        """Find algorithm blocks and return (start, end, content) tuples."""
        blocks = []

        # Pattern 1: "Algorithm N:" blocks
        alg_starts = list(re.finditer(
            r"(?:Algorithm|Procedure)\s+\d+[:\.]?\s*\n",
            text, re.IGNORECASE,
        ))

        for match in alg_starts:
            start = match.start()
            # Find end: next double newline or next section header
            end_match = re.search(
                r"\n\s*\n\s*(?:\d+\.?\s+[A-Z]|$)",
                text[match.end():],
            )
            if end_match:
                end = match.end() + end_match.start()
            else:
                end = min(start + 2000, len(text))

            blocks.append((start, end, text[start:end]))

        # Pattern 2: LaTeX algorithm environments
        for match in re.finditer(
            r"\\begin\{algorithm\}.*?\\end\{algorithm\}",
            text, re.DOTALL,
        ):
            blocks.append((match.start(), match.end(), match.group()))

        # Sort by start position and merge overlaps
        blocks.sort(key=lambda b: b[0])
        merged = []
        for block in blocks:
            if merged and block[0] <= merged[-1][1]:
                prev = merged[-1]
                new_end = max(prev[1], block[1])
                merged[-1] = (prev[0], new_end, text[prev[0]:new_end])
            else:
                merged.append(block)

        return merged

    def _extract_equation_chains(self, text: str) -> list[tuple[int, int]]:
        """Find groups of consecutive equations."""
        eq_positions = [
            (m.start(), m.end())
            for m in _EQUATION_PATTERN.finditer(text)
        ]

        if not eq_positions:
            return []

        # Group equations that are close together (within 200 chars)
        chains = []
        chain_start, chain_end = eq_positions[0]

        for start, end in eq_positions[1:]:
            if start - chain_end < 200:
                chain_end = end
            else:
                chains.append((chain_start, chain_end))
                chain_start, chain_end = start, end

        chains.append((chain_start, chain_end))
        return chains

    def _split_preserving_equations(
        self,
        text: str,
        section_name: str,
        eq_blocks: list[tuple[int, int]],
    ) -> list[Segment]:
        """Split text while keeping equation chains intact."""
        segments = []
        last_end = 0

        for eq_start, eq_end in eq_blocks:
            # Text before this equation chain
            if eq_start > last_end:
                pre_text = text[last_end:eq_start].strip()
                if pre_text:
                    if len(pre_text) <= self.max_chars:
                        segments.append(Segment(
                            content=pre_text,
                            section_name=section_name,
                            segment_type="text",
                        ))
                    else:
                        segments.extend(
                            self._split_by_paragraphs(pre_text, section_name)
                        )

            # The equation chain (keep intact)
            eq_text = text[eq_start:eq_end].strip()
            if eq_text:
                segments.append(Segment(
                    content=eq_text,
                    section_name=section_name,
                    segment_type="equation_block",
                    importance=0.9,
                ))
            last_end = eq_end

        # Remaining text
        if last_end < len(text):
            remaining = text[last_end:].strip()
            if remaining:
                if len(remaining) <= self.max_chars:
                    segments.append(Segment(
                        content=remaining,
                        section_name=section_name,
                        segment_type="text",
                    ))
                else:
                    segments.extend(
                        self._split_by_paragraphs(remaining, section_name)
                    )

        return segments

    # ------------------------------------------------------------------
    # Segment type detection and scoring
    # ------------------------------------------------------------------

    def _detect_segment_type(self, text: str) -> str:
        """Classify a chunk's type based on its content."""
        text_lower = text[:500].lower()

        if _ALGORITHM_PATTERN.search(text):
            return "algorithm"
        if text_lower.startswith("abstract"):
            return "abstract"
        if any(k in text_lower for k in ("method", "approach", "model", "architecture")):
            return "methods"
        if any(k in text_lower for k in ("experiment", "result", "evaluation", "ablation")):
            return "results"
        if _TABLE_PATTERN.search(text):
            return "table"
        if len(_EQUATION_PATTERN.findall(text)) > 3:
            return "equation_block"
        return "text"

    def _score_importance(
        self, segments: list[Segment], doc_type: str
    ) -> list[Segment]:
        """Assign importance scores to each segment."""
        # Importance weights by segment type (for code generation relevance)
        type_weights = {
            "algorithm": 0.95,
            "methods": 0.90,
            "equation_block": 0.85,
            "abstract": 0.70,
            "results": 0.40,
            "table": 0.30,
            "text": 0.50,
        }

        # Keywords that boost importance for code generation
        boost_keywords = {
            "loss function", "training", "forward pass", "backward",
            "gradient", "optimizer", "learning rate", "batch size",
            "architecture", "layer", "attention", "encoder", "decoder",
            "convolution", "embedding", "dimension", "hidden size",
            "implementation", "algorithm", "procedure", "pseudo",
        }

        for seg in segments:
            base = type_weights.get(seg.segment_type, 0.5)

            # Keyword boost
            text_lower = seg.content.lower()
            boost = sum(
                0.03 for kw in boost_keywords if kw in text_lower
            )
            seg.importance = min(base + boost, 1.0)

            # Extract keywords for query matching
            seg.keywords = self._extract_keywords(seg.content)

        return segments

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Extract salient keywords from a text chunk."""
        text_lower = text.lower()
        # Common ML/DL terms
        ml_terms = [
            "attention", "transformer", "convolution", "encoder", "decoder",
            "embedding", "loss", "gradient", "optimizer", "learning rate",
            "batch", "epoch", "layer", "hidden", "dimension", "softmax",
            "relu", "dropout", "normalization", "residual", "skip connection",
            "self-attention", "cross-attention", "multi-head", "feedforward",
            "positional encoding", "tokenizer", "vocabulary", "dataset",
            "training", "inference", "evaluation", "accuracy", "f1",
            "precision", "recall", "bleu", "perplexity",
        ]
        return [term for term in ml_terms if term in text_lower]

    # ------------------------------------------------------------------
    # Query-based retrieval
    # ------------------------------------------------------------------

    def _relevance_score(
        self,
        segment: Segment,
        query_words: set[str],
        query_type: str,
    ) -> float:
        """Score a segment's relevance to a query."""
        score = 0.0

        # Base importance
        score += segment.importance * 0.3

        # Keyword overlap
        seg_words = set(segment.content.lower().split())
        overlap = len(query_words & seg_words)
        if query_words:
            score += (overlap / len(query_words)) * 0.4

        # Keyword list match
        query_lower = " ".join(query_words)
        keyword_hits = sum(
            1 for kw in segment.keywords if kw in query_lower
        )
        score += min(keyword_hits * 0.1, 0.2)

        # Query type bonus
        type_bonus = {
            "concept_analysis": {"abstract": 0.1, "methods": 0.15},
            "algorithm_extraction": {"algorithm": 0.2, "methods": 0.1},
            "code_planning": {"methods": 0.15, "algorithm": 0.15, "equation_block": 0.1},
        }
        bonus_map = type_bonus.get(query_type, {})
        score += bonus_map.get(segment.segment_type, 0.0)

        return score
