# Research2Repo 🧪 ➡️ 💻

Research2Repo is an advanced, agentic framework designed to bridge the gap between academic machine learning research and functional codebase implementations. Specifically optimized for the Google Gemini ecosystem, it translates complex AI papers directly into modular, decoupled GitHub repositories.



## 🌟 Why Gemini? The Context Advantage

Traditional "Paper-to-Code" implementations rely on chunking and Retrieval-Augmented Generation (RAG) to handle long research papers. This often results in a loss of global context—where hyperparameters defined in an appendix become disconnected from the architectural equations in Section 3.

**Research2Repo uses a "Long-Context Single-Pass" architecture.** By leveraging Gemini 1.5 Pro's massive 2M+ token context window, the framework ingests the *entire* paper, supplemental tables, and mathematical proofs simultaneously. 
* **Zero-RAG Architecture:** Eliminates vector store overhead and retrieval hallucinations.
* **Multimodal Extraction:** Natively processes architecture diagrams (e.g., Transformer block flowcharts) using Gemini Vision, translating spatial representations directly into Mermaid.js diagrams or Python class skeletons.

## 🚀 Core Pipeline

1. **Analyzer (`core/analyzer.py`):** Ingests the PDF URL, extracts text, and identifies architectural diagrams for multimodal processing.
2. **Architect (`core/architect.py`):** Processes the global context to design the software architecture, defining `pyproject.toml`/`requirements.txt` and the repository tree.
3. **Coder (`core/coder.py`):** Synthesizes the final ML modules, ensuring strict adherence to the paper's defined loss functions, dimensions, and optimization strategies.

## 📦 Installation

```bash
git clone [https://github.com/your-org/Research2Repo.git](https://github.com/your-org/Research2Repo.git)
cd Research2Repo
pip install -r requirements.txt

Set your Google API Key:
```bash
export GEMINI_API_KEY="your_api_key_here"


## 💻 Usage
```bash
python main.py --pdf_url "[https://arxiv.org/pdf/1706.03762.pdf](https://arxiv.org/pdf/1706.03762.pdf)" --output_dir "./examples/attention_is_all_you_need"

