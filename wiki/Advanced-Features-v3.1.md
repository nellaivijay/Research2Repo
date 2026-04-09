# Advanced Features (v3.1) — DeepCode-Inspired

Research2Repo v3.1 integrates three novel techniques inspired by [HKUDS/DeepCode](https://github.com/HKUDS/DeepCode), adapted for Research2Repo's provider-agnostic multi-model architecture.

---

## 1. CodeRAG — Reference Code Mining & Indexing

**Module:** `advanced/code_rag.py`  
**CLI flag:** `--code-rag`  
**Default:** Disabled (opt-in)

### What It Does

CodeRAG searches GitHub for existing implementations related to your paper, downloads them, and uses the LLM to build confidence-scored mappings between reference code and your target file structure. During code generation, relevant reference snippets are injected as additional context.

### How It Works

```
Paper Analysis → [Generate Search Queries] → [GitHub Search API]
                                                      |
                                              Top repos by stars
                                                      |
                                          [Download & Index Files]
                                                      |
                                         [LLM Relevance Scoring]
                                                      |
                                    File-to-File Mappings with Confidence
```

#### Step 1: Query Generation
The LLM generates 3-5 GitHub search queries from the paper's title, architecture description, and key contributions:
```
Paper: "Attention Is All You Need"
→ Queries: ["pytorch transformer attention", "self-attention mechanism python", ...]
```

#### Step 2: GitHub Search
Queries are sent to the GitHub Search API (supports optional `GITHUB_TOKEN` for rate limits). Results are sorted by stars.

#### Step 3: File Indexing
From each repository, source files are fetched and prioritised:
1. Model/training/loss files first
2. Data/dataset files second
3. Config/utils/eval files third

#### Step 4: Relevance Mapping
Each reference file is analyzed by the LLM against your target file list. Mappings include:

| Relationship | Confidence | Meaning |
|-------------|-----------|---------|
| `direct_match` | 1.0 | Implements the same component |
| `partial_match` | 0.8 | Related component |
| `reference` | 0.6 | Useful architectural pattern |
| `utility` | 0.4 | Adaptable helper code |

#### Step 5: Context Injection
During code generation, `CodeRAG.get_reference_context()` retrieves the most relevant snippets for each target file.

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `code_rag_max_repos` | 3 | Max repositories to index |
| `code_rag_max_files` | 20 | Max files per repository |
| `GITHUB_TOKEN` env var | (none) | Optional token for higher API rate limits |

### Example Usage

```bash
# Enable CodeRAG in agent mode
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --code-rag

# CodeRAG works best with refine enabled
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --code-rag --refine
```

---

## 2. Document Segmenter — Semantic Paper Chunking

**Module:** `advanced/document_segmenter.py`  
**CLI flag:** `--no-segmentation` (to disable)  
**Default:** Enabled automatically when paper exceeds ~40,000 characters

### What It Does

When a paper's extracted text exceeds the token limit for a single LLM call, the DocumentSegmenter splits it into semantically meaningful chunks that preserve algorithm blocks, equation chains, and section boundaries.

### Segmentation Strategies

The segmenter automatically selects a strategy based on document analysis:

| Strategy | When Used | Key Feature |
|----------|----------|-------------|
| `semantic_research_focused` | Standard papers | Section-aware splitting |
| `algorithm_preserve_integrity` | Algorithm-heavy papers (density > 0.5) | Never splits mid-algorithm |
| `concept_implementation_hybrid` | Mixed algorithm + math papers | Preserves both algorithms and equation chains |
| `content_aware_segmentation` | ML/DL papers | Smaller chunks for method sections |

### Document Analysis Metrics

Before segmentation, the document is analysed:

- **Algorithm Density** (0.0–1.0): Detected via `Algorithm N:`, `Input:/Output:`, pseudocode patterns
- **Concept Complexity** (0.0–1.0): Equation blocks, LaTeX formulas, mathematical notation
- **Document Type**: `algorithm_focused`, `math_heavy`, `deep_learning`, `ml_training`, `research_paper`

### Key Features

1. **Algorithm Block Preservation**: Blocks like `Algorithm 1: ...` or `\begin{algorithm}...\end{algorithm}` are never split
2. **Equation Chain Grouping**: Consecutive equations within 200 characters are kept together
3. **Importance Scoring**: Each segment gets a score (0.0–1.0) based on type and content:
   - Algorithm blocks: 0.95
   - Methods sections: 0.90
   - Equation blocks: 0.85
   - Abstract: 0.70
   - Results/tables: 0.30–0.40
4. **Query-Aware Retrieval**: `query_segments()` ranks segments by relevance to a query

### Segment Data Model

```python
@dataclass
class Segment:
    content: str          # The text chunk
    section_name: str     # "Methods", "Algorithm", etc.
    segment_type: str     # text | algorithm | equation_block | table | abstract | methods
    importance: float     # 0.0 - 1.0
    keywords: list[str]   # Extracted ML/DL terms
```

---

## 3. Context Manager — Clean-Slate Generation

**Module:** `advanced/context_manager.py`  
**CLI flag:** `--no-context-manager` (to disable)  
**Default:** Enabled in agent mode

### The Problem

When generating 15-30 files, carrying the full conversation history causes context window overflow. The legacy approach (rolling window of last 3 files + dependencies) loses important information.

### The Solution: Clean-Slate + Cumulative Summaries

Inspired by DeepCode's "concise memory agent", the ContextManager:

1. **After each file is generated**: Produces a compact summary (classes, functions, algorithms, dependencies)
2. **Before each new file**: Rebuilds context from scratch using:
   - Static plan summary (always present)
   - Cumulative code summary (all prior files, compressed)
   - Full source of direct dependencies only
   - CodeRAG reference snippets (if available)
   - File-specific instructions

```
                                    ┌──────────────────────┐
                                    │   Plan Summary       │ (static)
                                    ├──────────────────────┤
                                    │ Cumulative Summary   │ (grows)
      After each file:              ├──────────────────────┤
      FileSummary{                  │ Dependency Code      │ (full source)
        classes, functions,    →    ├──────────────────────┤
        algorithms, deps            │ Reference Code       │ (CodeRAG)
      }                             ├──────────────────────┤
                                    │ File Instruction     │ (target file)
                                    └──────────────────────┘
                                         Context for each file
```

### File Summary Format

After each file, the summary captures:
```
### model/encoder.py (142 lines)
  Classes: TransformerEncoder, EncoderLayer
  Functions: generate_mask, positional_encoding
  Algorithms: scaled dot-product attention
  Deps: config.yaml, model/attention.py
```

### Benefits

| Metric | Legacy Rolling Window | Context Manager |
|--------|----------------------|-----------------|
| Context size for file #20 | Unpredictable (may overflow) | Bounded (~80K chars) |
| Cross-file coherence | Only recent 3 files | All files via summary |
| Dependency awareness | Truncated at 3000 chars | Full source for deps |
| Reference code | Not available | CodeRAG integration |

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `context_max_chars` | 80,000 | Target max context size |
| `context_use_llm_summaries` | `true` | Use LLM for summaries (falls back to heuristic) |

---

## Integration Architecture

All three modules integrate cleanly into the agent pipeline:

```
Stage 1: Parse Paper
Stage 2: Decomposed Planning
Stage 3: Per-File Analysis
Stage 3b: Document Segmentation (auto, if paper is large)
Stage 3c: CodeRAG (if --code-rag enabled)
Stage 4: Code Generation (ContextManager wraps CodeSynthesizer)
Stage 5-10: Tests, Validation, Execution, DevOps, Evaluation, Save
```

### Graceful Degradation

Each module is optional and fails gracefully:
- If `requests` isn't installed, CodeRAG skips GitHub search
- If no `GITHUB_TOKEN`, uses unauthenticated API (lower rate limits)
- If the LLM summary call fails, falls back to regex-based heuristic extraction
- If segmentation isn't needed (paper fits), it's skipped automatically
- Each module can be independently disabled via CLI flags

---

## API Reference

### CodeRAG

```python
from advanced.code_rag import CodeRAG, CodeRAGIndex

rag = CodeRAG(provider=my_provider, max_repos=3)
index: CodeRAGIndex = rag.build_index(analysis, plan)
context: str = rag.get_reference_context("model/encoder.py", index)
```

### DocumentSegmenter

```python
from advanced.document_segmenter import DocumentSegmenter, SegmentationResult

segmenter = DocumentSegmenter(max_chars_per_segment=12000)
result: SegmentationResult = segmenter.segment(paper_text)
relevant: list[Segment] = segmenter.query_segments(result, "attention mechanism")
```

### ContextManager

```python
from advanced.context_manager import ContextManager, GenerationContext

ctx_mgr = ContextManager(plan=plan, analysis=analysis, provider=provider)
for file_spec in plan.files:
    gen_ctx: GenerationContext = ctx_mgr.build_context(file_spec, ref_context="")
    code = provider.generate(prompt=gen_ctx.full_prompt(), ...)
    ctx_mgr.record_file(file_spec.path, code)
```
