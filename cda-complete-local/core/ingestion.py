"""
Repository Ingestion Module
Orchestrates the complete repository analysis pipeline:
1. File system scanning and manifest generation
2. Configuration file parsing (Docker, Serverless, Terraform, etc.)
3. Package dependency extraction (requirements.txt, package.json)
4. Token analysis for prompt files
5. Multi-language AST parsing (Python, JavaScript)
6. Pattern-based detection (regex sweep)

All operations run sequentially for stability and resource efficiency.
Author: Scrooge Scanner Team
"""
import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

# Import parsers
from core.parsers import (
    get_all_parsers,
    DockerfileParser,
    ServerlessParser,
    DockerComposeParser,
    TerraformParser,
    RequirementsParser,
    PackageJsonParser,
)

# Import token analyzer
from core.token_analyzer import TokenAnalyzer

# Import AST parsers
from core.ast_parsers.python_ast import PythonASTParser
from core.ast_parsers.javascript_ast import JavaScriptASTParser

# Import existing pattern detector
from core.pattern_detector import PatternDetector

logger = logging.getLogger(__name__)

# File extensions to ignore during scanning
IGNORED_EXTENSIONS = {
    '.pyc', '.pyo', '.pyd', '.so', '.dll', '.dylib',
    '.class', '.jar', '.war', '.ear',
    '.o', '.obj', '.a', '.lib',
    '.exe', '.bin', '.app',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico', '.svg',
    '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv',
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.min.js', '.min.css',  # Minified files
}

# Directories to ignore during scanning
IGNORED_DIRS = {
    '__pycache__', '.git', '.svn', '.hg', '.bzr',
    'node_modules', 'bower_components', 'jspm_packages',
    '.venv', 'venv', 'env', 'ENV', 'virtualenv',
    '.tox', '.nox', '.pytest_cache', '.mypy_cache',
    'build', 'dist', 'target', 'out', 'bin', 'obj',
    '.terraform', '.serverless',
    'coverage', '.coverage', 'htmlcov',
    '.idea', '.vscode', '.vs', '.eclipse',
}

# Maximum file size to analyze (10 MB)
MAX_FILE_SIZE = 10 * 1024 * 1024

def run_ingestion(repo_path: str, verbose: bool = False) -> Dict[str, Any]:
    """
    Main ingestion orchestrator.
    
    Runs all analysis phases sequentially:
    1. File system scan
    2. Config parsing
    3. Token analysis
    4. AST parsing
    5. Pattern detection
    
    Args:
        repo_path: Path to repository root
        verbose: Enable verbose logging
        
    Returns:
        Dictionary containing all extracted information:
        - manifest: List of all files with metadata
        - structure_map: Directory structure representation (for compatibility)
        - priority_files: High-value files for investigation
        - parsed_configs: List of parsed configuration files
        - token_analysis: Token counts for prompt files
        - ast_analysis: AST analysis for Python/JS files
        - sweep_report: Pattern detection results
    """
    repo_path = os.path.abspath(repo_path)
    
    if not os.path.isdir(repo_path):
        raise ValueError(f"Repository path does not exist: {repo_path}")
    
    if verbose:
        logger.info(f"Starting ingestion for: {repo_path}")
    
    # Phase 1: File System Scan
    if verbose:
        logger.info("Phase 1/5: Scanning file system...")
    manifest, structure_tree = _scan_filesystem(repo_path, verbose)
    
    # Phase 2: Configuration Parsing
    if verbose:
        logger.info("Phase 2/5: Parsing configuration files...")
    parsed_configs = _parse_configs(repo_path, manifest, verbose)
    
    # Phase 3: Token Analysis
    if verbose:
        logger.info("Phase 3/5: Analyzing token usage...")
    token_analysis = _analyze_tokens(repo_path, verbose)
    
    # Phase 4: AST Analysis
    if verbose:
        logger.info("Phase 4/5: Parsing source code AST...")
    ast_analysis = _parse_ast(repo_path, manifest, verbose)
    
    # Phase 5: Pattern Detection
    if verbose:
        logger.info("Phase 5/5: Running pattern detection...")
    sweep_report = _run_pattern_detection(repo_path, verbose)
    
    # Generate priority files list
    priority_files = _generate_priority_files(manifest, parsed_configs, ast_analysis)
    
    if verbose:
        logger.info("✅ Ingestion complete")
    
    # Return with compatibility keys for lambda_entrypoint.py
    return {
        'manifest': manifest,
        'structure_map': structure_tree,  # Renamed from structure_tree for compatibility
        'priority_files': priority_files,  # Added for compatibility
        'parsed_configs': parsed_configs,
        'token_analysis': token_analysis,
        'ast_analysis': ast_analysis,
        'sweep_report': sweep_report,
    }

def _scan_filesystem(repo_path: str, verbose: bool) -> tuple[List[Dict], str]:
    """
    Phase 1: Scan file system and build manifest.
    
    Returns:
        Tuple of (manifest, structure_tree)
    """
    manifest = []
    
    for root, dirs, files in os.walk(repo_path):
        # Filter out ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        
        for file in files:
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, repo_path)
            
            # Get file info
            try:
                stat = os.stat(file_path)
                size = stat.st_size
                
                # Skip large files
                if size > MAX_FILE_SIZE:
                    if verbose:
                        logger.debug(f"Skipping large file: {rel_path} ({size} bytes)")
                    continue
                
                # Skip ignored extensions
                ext = Path(file).suffix.lower()
                if ext in IGNORED_EXTENSIONS:
                    continue
                
                manifest.append({
                    'path': rel_path,
                    'name': file,
                    'ext': ext,
                    'size': size,
                    'dir': os.path.dirname(rel_path),
                })
                
            except (OSError, PermissionError) as e:
                if verbose:
                    logger.warning(f"Cannot access file {rel_path}: {e}")
                continue
    
    # Build structure tree (simplified version)
    structure_tree = _build_structure_tree(manifest)
    
    if verbose:
        logger.info(f"Scanned {len(manifest)} files")
    
    return manifest, structure_tree

def _build_structure_tree(manifest: List[Dict]) -> str:
    """Build a tree-like string representation of directory structure."""
    dirs = set()
    for item in manifest:
        dir_path = item['dir']
        if dir_path:
            dirs.add(dir_path)
    
    # Sort directories
    sorted_dirs = sorted(dirs)
    
    # Build tree (simplified - just list directories)
    tree_lines = ["Repository Structure:"]
    for dir_path in sorted_dirs[:50]:  # Limit to first 50 directories
        depth = dir_path.count(os.sep)
        indent = "  " * depth
        dir_name = os.path.basename(dir_path) or dir_path
        tree_lines.append(f"{indent}📁 {dir_name}/")
    
    if len(sorted_dirs) > 50:
        tree_lines.append(f"  ... and {len(sorted_dirs) - 50} more directories")
    
    return "\n".join(tree_lines)

def _parse_configs(
    repo_path: str,
    manifest: List[Dict],
    verbose: bool
) -> List[Dict[str, Any]]:
    """
    Phase 2: Parse configuration files.
    
    Returns:
        List of parsed configuration objects
    """
    # FIXED: Remove verbose parameter since get_all_parsers() doesn't accept it
    parsers = get_all_parsers()
    parsed_configs = []
    
    for file_item in manifest:
        file_path = os.path.join(repo_path, file_item['path'])
        
        # Try each parser
        for parser in parsers:
            try:
                result = parser.safe_parse(file_path)
                if result:
                    parsed_configs.append(result.dict())
                    break  # Move to next file once parsed
            except Exception as e:
                if verbose:
                    logger.debug(f"Parser {parser.__class__.__name__} failed on {file_path}: {e}")
                continue
    
    if verbose:
        logger.info(f"Parsed {len(parsed_configs)} configuration files")
    
    return parsed_configs

def _analyze_tokens(repo_path: str, verbose: bool) -> Dict[str, Any]:
    """
    Phase 3: Analyze token usage in prompt files.
    
    Returns:
        Dictionary with token analysis summary
    """
    try:
        analyzer = TokenAnalyzer(verbose=verbose)
        
        # Scan repository for prompt files
        prompt_analyses = analyzer.scan_repo_for_prompts(repo_path)
        
        # Generate summary
        summary = analyzer.generate_summary(prompt_analyses)
        
        if verbose:
            logger.info(
                f"Analyzed {summary['total_files']} prompt files, "
                f"estimated {summary['total_estimated_tokens']} tokens"
            )
        
        return summary
    except Exception as e:
        if verbose:
            logger.warning(f"Token analysis failed: {e}")
        return {
            'total_files': 0,
            'total_base_tokens': 0,
            'total_estimated_tokens': 0,
            'error': str(e)
        }

def _parse_ast(
    repo_path: str,
    manifest: List[Dict],
    verbose: bool
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Phase 4: Parse source code with AST.
    
    Returns:
        Dictionary with separate lists for Python and JavaScript analyses
    """
    try:
        python_parser = PythonASTParser(verbose=verbose)
        js_parser = JavaScriptASTParser(verbose=verbose)
        
        python_results = []
        javascript_results = []
        
        for file_item in manifest:
            file_path = os.path.join(repo_path, file_item['path'])
            
            try:
                # Parse Python files
                if python_parser.can_parse(file_path):
                    result = python_parser.parse_file(file_path)
                    if 'error' not in result:
                        python_results.append(result)
                
                # Parse JavaScript/TypeScript files
                elif js_parser.can_parse(file_path):
                    result = js_parser.parse_file(file_path)
                    if 'error' not in result:
                        javascript_results.append(result)
            except Exception as e:
                if verbose:
                    logger.debug(f"AST parsing failed for {file_path}: {e}")
                continue
        
        if verbose:
            logger.info(
                f"Parsed {len(python_results)} Python files, "
                f"{len(javascript_results)} JavaScript files"
            )
        
        return {
            'python': python_results,
            'javascript': javascript_results,
        }
    except Exception as e:
        if verbose:
            logger.warning(f"AST analysis failed: {e}")
        return {'python': [], 'javascript': [], 'error': str(e)}

def _run_pattern_detection(repo_path: str, verbose: bool) -> Dict[str, Any]:
    """
    Phase 5: Run pattern-based detection.
    
    Returns:
        Pattern detection report
    """
    try:
        detector = PatternDetector(verbose=verbose)
        
        # Run detection
        report = detector.sweep_repository(repo_path)
        
        # Count total hits
        total_hits = sum(len(matches) for matches in report.values())
        
        if verbose:
            logger.info(f"Pattern detection found {total_hits} matches")
        
        return report
    except Exception as e:
        if verbose:
            logger.warning(f"Pattern detection failed: {e}")
        return {'error': str(e)}

def _generate_priority_files(
    manifest: List[Dict],
    parsed_configs: List[Dict],
    ast_analysis: Dict
) -> List[str]:
    """
    Generate a prioritized list of files for investigation.
    
    Priority order:
    1. Configuration files (Dockerfile, serverless.yml, etc.)
    2. Main application entry points (main.py, index.js, app.py)
    3. Files with detected patterns
    4. Package dependency files
    5. Other source files
    """
    priority_files = []
    
    # High priority: Config files
    config_files = [c['file_path'] for c in parsed_configs if 'file_path' in c]
    priority_files.extend(config_files[:10])
    
    # Medium priority: Entry points and important files
    important_patterns = [
        'main.py', 'app.py', 'server.py', 'index.js', 'app.js', 'server.js',
        'requirements.txt', 'package.json', 'Pipfile', 'poetry.lock',
        'README.md', 'README.txt'
    ]
    
    for pattern in important_patterns:
        matches = [f['path'] for f in manifest if f['name'].lower() == pattern.lower()]
        priority_files.extend(matches)
    
    # Add Python files with interesting AST features
    if 'python' in ast_analysis:
        for py_file in ast_analysis['python'][:5]:
            if 'file_path' in py_file:
                priority_files.append(py_file['file_path'])
    
    # Add JavaScript files with interesting AST features
    if 'javascript' in ast_analysis:
        for js_file in ast_analysis['javascript'][:5]:
            if 'file_path' in js_file:
                priority_files.append(js_file['file_path'])
    
    # Deduplicate while preserving order
    seen = set()
    unique_priority = []
    for f in priority_files:
        if f not in seen:
            seen.add(f)
            unique_priority.append(f)
    
    return unique_priority[:30]  # Return top 30 priority files

def create_ingestion_summary(ingestion_result: Dict[str, Any]) -> str:
    """
    Create a human-readable summary of ingestion results.
    
    Args:
        ingestion_result: Result from run_ingestion()
        
    Returns:
        Formatted summary string
    """
    lines = [
        "=" * 60,
        "INGESTION SUMMARY",
        "=" * 60,
        "",
        f"📁 Files Scanned: {len(ingestion_result['manifest'])}",
        "",
        "📋 Configuration Files:",
    ]
    
    # Summarize parsed configs
    config_types = {}
    for config in ingestion_result['parsed_configs']:
        parser_type = config.get('parser_type', 'unknown')
        config_types[parser_type] = config_types.get(parser_type, 0) + 1
    
    for parser_type, count in config_types.items():
        lines.append(f"  - {parser_type}: {count} file(s)")
    
    if not config_types:
        lines.append("  - No configuration files found")
    
    # Token analysis
    token_summary = ingestion_result['token_analysis']
    lines.extend([
        "",
        "🔤 Token Analysis:",
        f"  - Prompt files: {token_summary.get('total_files', 0)}",
        f"  - Base tokens: {token_summary.get('total_base_tokens', 0):,}",
        f"  - Estimated tokens: {token_summary.get('total_estimated_tokens', 0):,}",
    ])
    
    # AST analysis
    ast_summary = ingestion_result['ast_analysis']
    lines.extend([
        "",
        "🌳 AST Analysis:",
        f"  - Python files: {len(ast_summary.get('python', []))}",
        f"  - JavaScript files: {len(ast_summary.get('javascript', []))}",
    ])
    
    # Pattern detection
    sweep_report = ingestion_result['sweep_report']
    if isinstance(sweep_report, dict) and 'error' not in sweep_report:
        total_patterns = sum(len(matches) for matches in sweep_report.values())
        lines.extend([
            "",
            "🔍 Pattern Detection:",
            f"  - Total matches: {total_patterns}",
        ])
        
        # Show top patterns
        sorted_patterns = sorted(
            sweep_report.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )
        
        for pattern_name, matches in sorted_patterns[:5]:
            lines.append(f"  - {pattern_name}: {len(matches)} match(es)")
    
    lines.extend(["", "=" * 60])
    
    return "\n".join(lines)

# Convenience function for command-line usage
def main():
    """Command-line entry point for testing."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python ingestion.py <repo_path>")
        sys.exit(1)
    
    repo_path = sys.argv[1]
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run ingestion
    result = run_ingestion(repo_path, verbose=True)
    
    # Print summary
    print("\n" + create_ingestion_summary(result))
    
    # Optionally save to file
    output_path = os.path.join(repo_path, 'ingestion_report.json')
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2, default=str)
    
    print(f"\n💾 Full report saved to: {output_path}")

if __name__ == '__main__':
    main()