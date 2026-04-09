"""
Advanced capabilities for Research2Repo.
"""

from advanced.equation_extractor import EquationExtractor
from advanced.config_generator import ConfigGenerator
from advanced.test_generator import TestGenerator
from advanced.cache import PipelineCache
from advanced.executor import ExecutionSandbox
from advanced.debugger import AutoDebugger
from advanced.evaluator import ReferenceEvaluator
from advanced.devops import DevOpsGenerator
from advanced.code_rag import CodeRAG
from advanced.document_segmenter import DocumentSegmenter
from advanced.context_manager import ContextManager

__all__ = [
    "EquationExtractor",
    "ConfigGenerator",
    "TestGenerator",
    "PipelineCache",
    "ExecutionSandbox",
    "AutoDebugger",
    "ReferenceEvaluator",
    "DevOpsGenerator",
    "CodeRAG",
    "DocumentSegmenter",
    "ContextManager",
]
