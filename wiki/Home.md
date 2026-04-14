# Research2Repo Wiki

**Multi-model agentic framework that converts ML research papers into production-ready GitHub repositories.**

Version 3.0 | Inspired by [PaperCoder](https://arxiv.org/abs/2504.17192) | Apache 2.0 License

---

## Quick Navigation

### Core Documentation
| Document | Description |
|----------|-------------|
| [Architecture Overview](Architecture-Overview) | System architecture, component interactions, design philosophy |
| [High-Level Design (HLD)](High-Level-Design) | Module responsibilities, pipeline flow, integration points |
| [Low-Level Design (LLD)](Low-Level-Design) | Class hierarchies, method contracts, algorithms, sequence diagrams |
| [Data Model](Data-Model) | All dataclasses, enums, schemas, and data flow between stages |

### Guides
| Document | Description |
|----------|-------------|
| [Usage Guide](Usage-Guide) | Installation, CLI reference, examples for both classic and agent modes |
| [Provider System & Configuration](Provider-System-and-Configuration) | Multi-model provider setup, auto-detection, capability routing |
| [Pipeline Stages Deep Dive](Pipeline-Stages-Deep-Dive) | Detailed walkthrough of all 10 stages in both modes |
| [Prompt Engineering Guide](Prompt-Engineering-Guide) | Template anatomy, placeholder system, customization guide |

### Operations
| Document | Description |
|----------|-------------|
| [API Reference](API-Reference) | Programmatic usage, class interfaces, method signatures |
| [Gateway Integration](Gateway-Integration) | Dual-mode architecture, Any2Repo-Gateway protocol, worked examples |
| [Deployment & DevOps](Deployment-and-DevOps) | Docker, CI/CD, production considerations |
| [Troubleshooting & FAQ](Troubleshooting-and-FAQ) | Common issues, debugging tips, FAQ |

---

## Project Overview

Research2Repo automates the conversion of ML research papers (PDFs) into fully functional GitHub repositories. Given a paper URL, the system:

1. **Parses** the paper using long-context LLMs (up to 2M tokens with Gemini)
2. **Plans** the repository structure through decomposed multi-stage planning
3. **Analyzes** each file specification before code generation
4. **Generates** production-quality code with rolling dependency context
5. **Validates** output against the paper's equations, hyperparameters, and architecture
6. **Executes** generated code in a sandbox and auto-debugs failures
7. **Produces** DevOps artifacts (Dockerfile, CI, Makefile)

### Dual Pipeline Modes

| Mode | Description | Best For |
|------|-------------|----------|
| **Classic** (`--mode classic`) | Original v2.0 linear pipeline, 10 stages | Fast generation, simple papers |
| **Agent** (`--mode agent`) | v3.0 enhanced pipeline with decomposed planning, self-refine, execution | Complex papers, production quality |

### Supported Providers

| Provider | Models | Context Window | Vision | Cost |
|----------|--------|---------------|--------|------|
| **Google Gemini** | 2.5 Pro, 2.0 Flash, 1.5 Pro | 1M-2M tokens | Yes | $0.0001-$0.01/1K |
| **OpenAI** | GPT-4o, GPT-4-turbo, o3, o1 | 128K-200K tokens | Yes | $0.0025-$0.06/1K |
| **Anthropic** | Claude Sonnet 4, Opus 4, 3.5 Sonnet | 200K tokens | Yes | $0.003-$0.075/1K |
| **Ollama** | DeepSeek, Llama 3.1, CodeLlama, Mistral | 4K-128K tokens | Partial | Free (local) |

### Key Metrics

| Metric | Value |
|--------|-------|
| Python files | 31 |
| Total Python lines | ~8,250 |
| Prompt templates | 16 |
| Pipeline stages (agent mode) | 10 |
| Supported LLM providers | 4 |
| Error types auto-debugged | 19+ |

---

## Getting Started

```bash
# Clone and install
git clone https://github.com/nellaivijay/Research2Repo.git
cd Research2Repo
pip install -r requirements.txt

# Set up a provider
export GEMINI_API_KEY="your_key_here"

# Run (classic mode)
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf"

# Run (agent mode with all features)
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" \
  --mode agent --refine --execute
```

See the [Usage Guide](Usage-Guide) for complete instructions.
