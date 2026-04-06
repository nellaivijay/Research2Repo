"""
Research2Repo: End-to-end execution pipeline.
Demonstrates the flow from a research paper PDF URL to a generated local repository.
"""

import os
import argparse
import requests
import google.generativeai as genai
from core.analyzer import PaperAnalyzer
from core.architect import SystemArchitect
from core.coder import CodeSynthesizer

def download_pdf(url: str, save_path: str) -> str:
    """Downloads the target research paper."""
    print(f"[*] Downloading PDF from {url}...")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(save_path, 'wb') as f:
        f.write(response.content)
    return save_path

def main(pdf_url: str, output_dir: str):
    # 1. Initialization & Setup
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Please set the GEMINI_API_KEY environment variable.")
    
    genai.configure(api_key=api_key)
    os.makedirs(output_dir, exist_ok=True)
    temp_pdf_path = os.path.join(output_dir, "source_paper.pdf")

    try:
        # 2. Download Source Material
        download_pdf(pdf_url, temp_pdf_path)

        # 3. Analyze (Long-Context & Multimodal Extraction)
        print("[*] Initializing Gemini 1.5 Pro Long-Context Analyzer...")
        analyzer = PaperAnalyzer(model_name='gemini-1.5-pro')
        
        # Uploading file directly via Generative AI File API for massive context
        uploaded_doc = analyzer.upload_document(temp_pdf_path)
        extracted_vision_context = analyzer.extract_diagrams_to_mermaid(temp_pdf_path)

        # 4. Architect (System Design & Dependencies)
        print("[*] Architecting repository structure...")
        architect = SystemArchitect()
        repo_structure, requirements_content = architect.design_system(
            document=uploaded_doc, 
            vision_context=extracted_vision_context
        )

        # Write dependencies
        with open(os.path.join(output_dir, "requirements.txt"), "w") as f:
            f.write(requirements_content)

        # 5. Coder (Modular Code Generation)
        print("[*] Synthesizing ML modules...")
        coder = CodeSynthesizer()
        generated_files = coder.generate_codebase(
            document=uploaded_doc,
            architecture_plan=repo_structure
        )

        # 6. Save outputs
        for filepath, content in generated_files.items():
            full_path = os.path.join(output_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(content)
            print(f"  -> Created {filepath}")

        print(f"\n[+] Repository successfully generated at: {output_dir}")

    finally:
        # Cleanup
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Research2Repo execution script.")
    parser.add_argument("--pdf_url", type=str, required=True, help="URL of the arXiv PDF.")
    parser.add_argument("--output_dir", type=str, default="./generated_repo", help="Target directory.")
    
    args = parser.parse_args()
    main(args.pdf_url, args.output_dir)
