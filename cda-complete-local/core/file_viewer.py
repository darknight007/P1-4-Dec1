import os
import re
import filetype # NEW IMPORT

# --- CONFIGURABLE LIMITS ---
MAX_LINES_DEFAULT = 500  # Default max lines to return for read_file
MAX_FILE_SIZE_KB = 250   # Max KB for a file to be read fully
REDACTION_PATTERNS = [
    re.compile(r'(AKIA|ASIA|AGIA|AIDA)[0-9A-Z]{16}'),  # AWS Access Key ID
    re.compile(r'[0-9a-zA-Z/+]{40}={0,2}'),            # Potential AWS Secret Access Key (base64)
    re.compile(r'(sk|pk|rk)_[0-9a-zA-Z]{32,64}'),      # Stripe, Public/Private/Refresh keys
    re.compile(r'oauth[2]?[a-zA-Z0-9_\-]{16,64}'),     # Generic OAuth tokens
    re.compile(r'[a-f0-9]{32}'),                       # Generic MD5/API keys
    re.compile(r'[a-f0-9]{40}'),                       # Generic SHA1 keys
    re.compile(r'[a-f0-9]{64}'),                       # Generic SHA256 keys
]

# --- HELPER FUNCTIONS ---

def detect_binary_file(file_path: str) -> bool:
    """Detects if a file is binary using the filetype library."""
    try:
        kind = filetype.guess(file_path)
        return kind is not None # If filetype can guess, it's usually not plain text
    except Exception:
        return False # Default to not binary if guess fails

def redact_secrets(content: str) -> str:
    """Redacts known secret patterns from the content."""
    for pattern in REDACTION_PATTERNS:
        content = pattern.sub('[REDACTED]', content)
    return content

# --- CORE LOGIC ---

def read_file_safe(file_path: str, root_path: str, start_line: int = 1, end_line: int = None) -> str:
    """
    Reads a file safely with pagination support, file size limits, binary detection, and secret redaction.
    """
    abs_root = os.path.abspath(root_path)
    abs_path = os.path.abspath(os.path.join(abs_root, file_path))

    # Security Check: Ensure file is within the project root
    if not abs_path.startswith(abs_root):
        return f"Error: Access denied. {file_path} is outside the project root."

    if not os.path.exists(abs_path):
        return f"Error: File {file_path} not found."
    
    # Check if it's a directory
    if os.path.isdir(abs_path):
        return f"Error: {file_path} is a directory, not a file. Use list_directories instead."

    # Binary File Check
    if detect_binary_file(abs_path):
        return f"Error: {file_path} is a binary file and cannot be read."

    # File Size Check
    file_size_kb = os.path.getsize(abs_path) / 1024
    if file_size_kb > MAX_FILE_SIZE_KB:
        return f"Error: File {file_path} (size: {file_size_kb:.2f}KB) exceeds the maximum allowed size of {MAX_FILE_SIZE_KB}KB. Use 'read_file_safe' with start_line/end_line to read specific parts if absolutely necessary."

    try:
        content_lines = []
        current_line = 1
        lines_read = 0
        truncated_by_line_limit = False
        
        # Validate inputs
        if start_line < 1: start_line = 1
        
        with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if current_line < start_line:
                    current_line += 1
                    continue
                
                if end_line is not None and current_line > end_line:
                    break

                if lines_read >= MAX_LINES_DEFAULT:
                    truncated_by_line_limit = True
                    break

                content_lines.append(line)
                lines_read += 1
                current_line += 1

        # Join content and redact secrets
        full_content = "".join(content_lines)
        redacted_content = redact_secrets(full_content)

        # Append truncation message if needed
        if truncated_by_line_limit:
            redacted_content += f"\n... [Truncated: Displaying {MAX_LINES_DEFAULT} lines. Use start_line={current_line} to read more] ..."

        # Feedback
        range_str = f"{start_line}-{current_line-1}"
        trunc_msg = " [Truncated]" if truncated_by_line_limit or file_size_kb > MAX_FILE_SIZE_KB else ""
        print(f"   📄 \033[96mReading\033[0m {file_path} (Lines {range_str}){trunc_msg}")

        if lines_read == 0 and not truncated_by_line_limit: # Only if nothing was read and not due to truncation
            return f"File {file_path} exists but lines {start_line}-{end_line if end_line else 'end'} appear empty or out of bounds."
        
        return redacted_content

    except Exception as e:
        return f"Error reading file: {str(e)}"